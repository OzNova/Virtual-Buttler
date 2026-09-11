(function(){
  var $ = function(id){ return document.getElementById(id); };

  var selected = [];
  var duration = 2;
  var mode = "practice";
  var criterion = "A";
  var timerInt = null;
  var lastPlan = null;
  var lastMeta = null;
  var timerState = {
    activeBlockId: null,
    isRunning: false,
    remainingSeconds: 0,
    targetEndTs: 0
  };
  var renderAnchorId = null;
  var audioCtx = null;
  var completionFired = false;
  var zenActive = false;
  var zenBlockId = null;
  var zenAbandonPending = null;
  var zenAbandoning = false;
  var zenModalOpen = false;
  var lofiNodes = null;
  var spaceNodes = null;

  function ensureAudio(){
    try {
      if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === "suspended") audioCtx.resume();
    } catch(e){ audioCtx = null; }
    return audioCtx;
  }

  function playChime(){
    var ctx = ensureAudio();
    if (!ctx) return;
    function strike(freq, delay){
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      var t = ctx.currentTime + delay;
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.22, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 1.4);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 1.5);
    }
    strike(880, 0);
    strike(1318.51, 0.01);
    strike(1174.66, 0.3);
    strike(1760, 0.31);
  }

  function notifyComplete(block){
    var title = "☕ Mola Zamanı!";
    var who = (block.subject ? block.subject + " · " : "") + block.topic;
    var body = "Time for a break! " + who + " seansı tamamlandı. 10 dk dinlen.";
    if ("Notification" in window && Notification.permission === "granted"){
      try { new Notification(title, { body: body, icon: "/static/icon-192.png" }); } catch(e){}
    }
    setMsg("⏰ " + title + " " + block.topic + " seansı tamamlandı — mola vakti!", "ok");
  }

  function startLoFi(){
    if (lofiNodes) return;
    var ctx = ensureAudio(); if (!ctx) return;
    var master = ctx.createGain(); master.gain.value = 0.065; master.connect(ctx.destination);
    var nodes = [];
    [130.81, 164.81, 196.00].forEach(function(f, i){
      var o = ctx.createOscillator(); o.type = "sine"; o.frequency.value = f; o.detune.value = (i - 1) * 7;
      var g = ctx.createGain(); g.gain.value = 0.55;
      var lfo = ctx.createOscillator(); lfo.type = "sine"; lfo.frequency.value = 0.14 + i * 0.08;
      var lg = ctx.createGain(); lg.gain.value = 0.14;
      lfo.connect(lg); lg.connect(g.gain); o.connect(g); g.connect(master);
      o.start(); lfo.start(); nodes.push(o, lfo);
    });
    lofiNodes = { master: master, oscs: nodes };
  }
  function stopLoFi(){
    if (!lofiNodes) return;
    lofiNodes.oscs.forEach(function(o){ try { o.stop(); } catch(e){} });
    lofiNodes.master.disconnect(); lofiNodes = null;
  }
  function startSpace(){
    if (spaceNodes) return;
    var ctx = ensureAudio(); if (!ctx) return;
    var master = ctx.createGain(); master.gain.value = 0.055; master.connect(ctx.destination);
    var nodes = [];
    [36.7, 55, 73.42].forEach(function(f){
      var o = ctx.createOscillator(); o.type = "sine"; o.frequency.value = f;
      var g = ctx.createGain(); g.gain.value = 0.5;
      var lfo = ctx.createOscillator(); lfo.type = "sine"; lfo.frequency.value = 0.04 + Math.random() * 0.06;
      var lg = ctx.createGain(); lg.gain.value = 0.11;
      lfo.connect(lg); lg.connect(g.gain); o.connect(g); g.connect(master);
      o.start(); lfo.start(); nodes.push(o, lfo);
    });
    spaceNodes = { master: master, oscs: nodes };
  }
  function stopSpace(){
    if (!spaceNodes) return;
    spaceNodes.oscs.forEach(function(o){ try { o.stop(); } catch(e){} });
    spaceNodes.master.disconnect(); spaceNodes = null;
  }

  function fetchSchool(){
    fetch("/api/school").then(function(r){ return r.json(); }).then(function(d){
      if (d.status === "success") renderSchool(d.school);
    }).catch(function(){});
  }
  function renderSchool(s){
    var ss = $("school-strip");
    if (!ss){ return; }
    if (!s || !s.date){ ss.className = "school-strip"; ss.hidden = true; return; }
    ss.className = "school-strip show" + (s.status === "school" ? "" : " off");
    ss.hidden = false;
    $("ss-badge").textContent = s.status === "school" ? "🏫 DERS GÜNÜ" : "🌤 SERBEST";
    if (s.status === "school"){
      $("ss-subjects").textContent = "Bugün: " + (s.subjects_today || []).join(" · ");
      $("ss-meta").textContent = s.day + " · okul " + s.school_window + " · öğle " + s.lunch + " · çalışma sonrası";
      $("ss-note").textContent = "yarın: " + (s.subjects_next_day || []).join(" · ");
    } else {
      $("ss-subjects").textContent = (s.status_label || "Serbest gün");
      $("ss-meta").textContent = s.day + " · tüm gün serbest";
      $("ss-note").textContent = "";
    }
  }

  function fetchGame(){
    fetch("/api/game").then(function(r){ return r.json(); }).then(function(d){
      if (d.status === "success"){
        renderGame(d);
        var el = $("streak");
        if (el) el.textContent = "🔥 " + (d.streak || 0) + " Günlük Seri";
      }
    }).catch(function(){});
  }
  function renderGame(g){
    var lv = $("gc-level"); if (lv) lv.textContent = "Level " + g.level;
    var md = $("gc-modules");
    if (md){
      md.innerHTML = "";
      for (var i = 0; i < g.base_modules; i++){
        var m = document.createElement("span"); m.className = "gc-mod"; md.appendChild(m);
      }
    }
    var fl = $("gc-fill");
    if (fl) fl.style.width = Math.min(100, ((g.xp % (g.xp_next || 100)) / (g.xp_next || 100)) * 100).toFixed(1) + "%";
    var xn = $("gc-xp"); if (xn) xn.textContent = g.xp + " XP / " + g.xp_next;
    var bi = $("gc-base"); if (bi) bi.classList.toggle("damaged", g.base_health === "damaged");
    var bc = $("gc-badges");
    if (bc){
      bc.innerHTML = "";
      (g.badges || []).forEach(function(bg){
        var el = document.createElement("span"); el.className = "gc-badge"; el.textContent = bg; bc.appendChild(el);
      });
    }
  }

  function resetZenState(fullClean){
    zenModalOpen = false;
    zenAbandonPending = null;
    zenAbandoning = false;
    $("zen-confirm").hidden = true;
    $("zen-overlay").hidden = true;
    stopLoFi(); stopSpace();
    if (fullClean){
      zenActive = false;
      zenBlockId = null;
      timerState.activeBlockId = null;
      timerState.isRunning = false;
      timerState.targetEndTs = 0;
      timerState.remainingSeconds = 0;
      completionFired = false;
      $("zen-splash").hidden = true;
    }
  }
  function enterZenMode(block){
    resetZenState(false);
    zenActive = true; zenBlockId = block.id;
    var zl = $("zen-lofi"), zs2 = $("zen-space");
    if (zl) zl.classList.remove("on");
    if (zs2) zs2.classList.remove("on");
    var zsub = $("zen-subject"), ztop = $("zen-topic"), zcd = $("zen-countdown");
    if (zsub) zsub.textContent = block.subject || "";
    if (ztop) ztop.textContent = block.topic || "";
    if (zcd) zcd.textContent = fmt(timerState.remainingSeconds || blockSeconds(block));
    var zf = $("zen-fill"); if (zf) zf.style.width = "0%";
    var zs = $("zen-status"); if (zs) zs.textContent = "Seans devam ediyor...";
    $("zen-overlay").hidden = false;
    ensureAudio();
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
  }
  function exitZenMode(){
    resetZenState(false);
    zenActive = false; zenBlockId = null;
  }
  function openZenConfirm(){
    if (!zenActive || !zenBlockId) return;
    zenModalOpen = true;
    zenAbandoning = false;
    $("zen-confirm").hidden = false;
  }
  function closeZenConfirm(){
    if (!zenModalOpen) return;
    zenModalOpen = false;
    zenAbandonPending = null;
    $("zen-confirm").hidden = true;
  }
  function doAbandonZen(){
    var blk = zenAbandonPending;
    if (!blk || zenAbandoning) return;
    zenAbandoning = true;
    resetZenState(true);
    setMsg("✕ Seans sonlandırıldı — inşaat modülü hasarlandı.", "ok");
    adjust({ action: "done", id: blk.id, zen_abandon: true }, function(){
      fetchGame();
    });
  }
  function showZenSplash(title, detail, fullSuccess){
    resetZenState(false);
    zenActive = false; zenBlockId = null;
    $("zen-splash-title").textContent = title;
    $("zen-splash-detail").textContent = detail;
    $("zen-splash-icon").textContent = fullSuccess ? "🚀" : "⚠️";
    $("zen-splash").hidden = false;
    fetchGame();
  }

  function updateStats(){
    var blocks = lastPlan || [];
    var target = 0, doneSec = 0, doneCount = 0, totalCount = 0;
    var nowSec = Math.floor(Date.now() / 1000);
    blocks.forEach(function(b){
      if (b.type !== "study" || b.status === "pushed") return;
      totalCount++;
      target += b.duration;
      if (b.status === "done"){ doneCount++; doneSec += b.duration * 60; }
      else if (b.active){ doneSec += Math.min(b.duration * 60, blockElapsedTotal(b, nowSec)); }
    });
    $("st-total").textContent = target;
    $("st-done").textContent = Math.round(doneSec / 60);
    $("st-count").textContent = doneCount + "/" + totalCount;
    var pct = target ? Math.min(100, (doneSec / (target * 60)) * 100) : 0;
    var fill = $("st-fill");
    if (fill){
      var wpct = pct.toFixed(1) + "%";
      if (fill.style.width !== wpct) fill.style.width = wpct;
    }
    var pc = $("st-pct");
    if (pc) pc.textContent = Math.round(pct) + "%";
    syncMasterNote(blocks, target);
  }

  function syncMasterNote(blocks, target){
    var note = $("tl-note");
    if (!note || !lastMeta) return;
    var parts = [];
    if (lastMeta.fit && lastMeta.fit.scaled){
      parts.push("⚠ " + lastMeta.fit.topic_count + " konu için en az " + lastMeta.fit.required_hours + " saat gerekli — bloklar ölçeklendi");
    }
    parts.push(blocks.length + " blok · " + target + " dk odak");
    if (lastMeta.dropped && lastMeta.dropped.length){
      parts.push("Sığmayan: " + lastMeta.dropped.join(", "));
    }
    note.textContent = parts.join(" · ");
  }

  function setMsg(text, kind){
    var m = $("msg");
    m.textContent = text || "";
    m.className = kind || "";
  }

  function findSel(subject, topic){
    for (var i = 0; i < selected.length; i++){
      if (selected[i].subject === subject && selected[i].topic === topic) return selected[i];
    }
    return null;
  }

  function rebuildChips(){
    var box = $("sel-topics");
    box.innerHTML = "";
    selected.forEach(function(it){
      var badge = document.createElement("span");
      badge.className = "badge c-" + it.confidence;

      var top = document.createElement("span");
      top.className = "b-top";
      top.textContent = it.topic;

      var x = document.createElement("button");
      x.type = "button";
      x.className = "xch";
      x.textContent = "✕";
      x.addEventListener("click", function(){ toggleTopic(it.subject, it.topic); });
      top.appendChild(x);
      badge.appendChild(top);

      var cf = document.createElement("span");
      cf.className = "cf";
      [["red","🔴"],["yellow","🟡"],["green","🟢"]].forEach(function(ci){
        var b = document.createElement("button");
        b.type = "button";
        b.title = ci[1] + " " + ({red:"Zorlanıyorum",yellow:"Orta",green:"Hakimim"})[ci[0]];
        b.textContent = ci[1];
        if (it.confidence === ci[0]) b.classList.add("on");
        b.addEventListener("click", function(){ it.confidence = ci[0]; rebuildChips(); });
        cf.appendChild(b);
      });
      badge.appendChild(cf);

      box.appendChild(badge);
    });
    if (!selected.length){
      var e = document.createElement("span");
      e.className = "sel-empty";
      e.textContent = "Henüz konu seçilmedi.";
      box.appendChild(e);
    }
    $("sel-count").textContent = selected.length;
    $("go").disabled = selected.length === 0;
  }

  function findPill(subject, topic){
    var pills = document.querySelectorAll(".pill[data-topic]");
    for (var i = 0; i < pills.length; i++){
      if (pills[i].dataset.subject === subject && pills[i].dataset.topic === topic) return pills[i];
    }
    return null;
  }

  function toggleTopic(subject, topic){
    var it = findSel(subject, topic);
    var pill = findPill(subject, topic);
    if (it){
      selected.splice(selected.indexOf(it), 1);
      if (pill) pill.classList.remove("active");
    } else {
      selected.push({ subject: subject, topic: topic, confidence: "yellow" });
      if (pill) pill.classList.add("active");
    }
    rebuildChips();
  }

  function injectTopic(subject, topic){
    var it = findSel(subject, topic);
    if (it){ it.confidence = "red"; }
    else {
      selected.push({ subject: subject, topic: topic, confidence: "red" });
      var pill = findPill(subject, topic);
      if (pill) pill.classList.add("active");
    }
    rebuildChips();
    setMsg("Zayıf konu plana 🔴 olarak eklendi.", "ok");
    submitPlan(true);
  }

  document.addEventListener("click", function(e){
    var pill = e.target.closest(".pill[data-topic]");
    if (pill){ toggleTopic(pill.dataset.subject, pill.dataset.topic); return; }
    var dur = e.target.closest("#dur-pills .pill[data-dur]");
    if (dur){
      document.querySelectorAll("#dur-pills .pill").forEach(function(p){ p.classList.remove("active"); });
      dur.classList.add("active");
      duration = parseInt(dur.dataset.dur, 10);
      var startMin = parseTimeToMin($("win-s").value);
      $("win-e").value = minToTimeStr(startMin + duration * 60);
      updateDefaultText();
      return;
    }
    var m = e.target.closest("#mode-pills .pill[data-mode]");
    if (m){
      document.querySelectorAll("#mode-pills .pill").forEach(function(p){ p.classList.remove("active"); });
      m.classList.add("active");
      mode = m.dataset.mode;
      return;
    }
    var c = e.target.closest("#cri-pills .pill[data-cri]");
    if (c){
      document.querySelectorAll("#cri-pills .pill").forEach(function(p){ p.classList.remove("active"); });
      c.classList.add("active");
      criterion = c.dataset.cri;
    }
  });

  $("win-s").addEventListener("input", syncPillFromTimes);
  $("win-e").addEventListener("input", syncPillFromTimes);

  $("sel-clear").addEventListener("click", function(){
    selected.forEach(function(it){ var p = findPill(it.subject, it.topic); if (p) p.classList.remove("active"); });
    selected = [];
    rebuildChips();
  });

  function blockEl(b){
    var div = document.createElement("div");
    div.className = "pblock";
    div.setAttribute("data-bid", b.id);
    var running = !!b.active;
    var timerPaused = !b.active && (b.elapsed || 0) > 0;
    if (b.type === "break") div.className += " break";
    else {
      div.className += " study c-" + b.confidence;
      if (b.isReview) div.className += " review";
      if (b.isRescheduled) div.className += " rescheduled";
      if (b.status === "pushed") div.className += " pushed";
      if (running) div.className += " active running";
      if (timerPaused) div.className += " timer-paused";
      if (b.status === "done") div.className += " done";
    }

    var row = document.createElement("div");
    row.className = "prow";

    var time = document.createElement("div");
    time.className = "ptime";
    time.textContent = b.time;
    row.appendChild(time);

    var mid = document.createElement("div");
    mid.className = "pmid";
    if (b.type === "break"){
      var br = document.createElement("div");
      br.className = "ptitle";
      br.textContent = "☕ Mola";
      mid.appendChild(br);
    } else {
      var title = document.createElement("div");
      title.className = "ptitle";
      title.textContent = b.topic;
      var sub = document.createElement("div");
      sub.className = "psub";
      if (b.isReview){
        sub.textContent = b.subject + " · 15 dk";
        var rbadge = document.createElement("span");
        rbadge.className = "review-badge";
        rbadge.textContent = "🧠 " + (b.reviewLabel || "Spaced Review");
        sub.appendChild(rbadge);
      } else {
        sub.textContent = b.subject + " · " + b.duration + " dk";
        if (b.isRescheduled){
          var rres = document.createElement("span");
          rres.className = "res-badge";
          rres.textContent = "⏰ Rescheduled";
          sub.appendChild(rres);
        }
      }
      var tag = document.createElement("div");
      tag.className = "ptag";
      if (b.isReview){
        tag.className += " review";
        tag.textContent = "🧠 Spaced Review · 15 dk";
      } else if (b.isRescheduled){
        tag.className += " rescheduled";
        tag.textContent = "⏰ Rescheduled";
      } else if (b.status === "pushed"){
        tag.className += " m";
        tag.textContent = "⏩ Yarına itelendi";
      } else {
        tag.className += " " + b.confidence[0];
        tag.textContent = {red:"🔴 Zorlanıyorum · Deep Focus", yellow:"🟡 Orta · Practice", green:"🟢 Hakimim · Quick Review"}[b.confidence];
      }
      mid.appendChild(title);
      mid.appendChild(sub);
      mid.appendChild(tag);
      if (b.status !== "pushed"){
        var stat = document.createElement("div");
        stat.className = "pstat";
        stat.setAttribute("data-bid", b.id);
        if (b.status === "done"){
          stat.className += " done";
          stat.textContent = "✅ Tamamlandı";
        }
        mid.appendChild(stat);
      }
    }
    var notes = document.createElement("div");
    notes.className = "pnotes";
    if (b.type === "study" && b.active){
      notes.textContent = "▶ Derin odak sürüyor — " + b.note;
    } else {
      notes.textContent = b.note;
    }
    mid.appendChild(notes);
    row.appendChild(mid);

    if (b.type === "study" && b.id === renderAnchorId){
      var panel = document.createElement("div");
      panel.className = "timer-panel";

      var badge = document.createElement("span");
      badge.className = "timer-state-badge " + (running ? "run" : "pause");
      badge.textContent = running ? "▶ RUNNING" : "⏸ PAUSED";
      panel.appendChild(badge);

      var ct = document.createElement("span");
      ct.className = "ctimer";
      ct.setAttribute("data-bid", b.id);
      ct.textContent = "00:00";
      panel.appendChild(ct);

      var prog = document.createElement("div");
      prog.className = "progress";
      var fill = document.createElement("div");
      fill.className = "progress-fill";
      fill.setAttribute("data-bid", b.id);
      prog.appendChild(fill);
      panel.appendChild(prog);

      var qacts = document.createElement("div");
      qacts.className = "timer-quick-acts";

      var ext = document.createElement("button");
      ext.type = "button";
      ext.className = "qbtn ext";
      ext.textContent = "+5 Dk";
      ext.title = "Sayacı 5 dakika uzat";
      ext.addEventListener("click", function(){
        if (timerState.activeBlockId !== b.id) return;
        extendTimer(b);
      });
      qacts.appendChild(ext);

      var fin = document.createElement("button");
      fin.type = "button";
      fin.className = "qbtn fin";
      fin.textContent = "Erken Bitir";
      fin.title = "Seansı tamamla ve sıradaki bloğa geç";
      fin.addEventListener("click", function(){
        if (timerState.activeBlockId !== b.id) return;
        finishEarly(b);
      });
      qacts.appendChild(fin);

      panel.appendChild(qacts);
    }

    if (b.type === "study" && running){
      var go = document.createElement("span");
      go.className = "pgo";
      go.textContent = "▶ ŞİMDİ";
      row.appendChild(go);
    }
    div.appendChild(row);

    if (b.type === "study" && b.id === renderAnchorId) div.appendChild(panel);

    if (b.type === "study"){
      var acts = document.createElement("div");
      acts.className = "pacts";

      var a1 = document.createElement("button");
      a1.type = "button";
      if (running){
        a1.textContent = "⏸ Duraklat";
        a1.classList.add("pause-btn");
      } else {
        a1.textContent = (b.elapsed || 0) > 0 ? "▶ Devam Et" : "▶ Şimdi Başlat";
        if (b.status !== "pushed") a1.classList.add("play-btn");
      }
      a1.addEventListener("click", function(){
        var isCurrentlyActive = b.active;
        if (!isCurrentlyActive){
          timerState.activeBlockId = null;
          timerState.isRunning = false;
          timerState.targetEndTs = 0;
          timerState.remainingSeconds = blockSeconds(b);
          completionFired = false;
          adjust({ action: "start", id: b.id }, function(){ enterZenMode(b); });
        } else {
          adjust({ action: "stop", id: b.id }, function(){ exitZenMode(); });
        }
      });
      acts.appendChild(a1);

      if (b.active || (b.elapsed || 0) > 0){
        var aReset = document.createElement("button");
        aReset.type = "button";
        aReset.textContent = "↺ Zamanı Sıfırla";
        aReset.title = "Sayacı sıfırla (durdurmaz)";
        aReset.addEventListener("click", function(){
          adjust({ action: "reset", id: b.id });
        });
        acts.appendChild(aReset);
      }

      var a2 = document.createElement("button");
      a2.type = "button";
      a2.textContent = b.status === "pushed" ? "↩ Bugüne Döndür" : "⏩ Yarın Etiketiyle İtele";
      if (b.status !== "pushed") a2.classList.add("warn");
      a2.addEventListener("click", function(){
        adjust({ action: b.status === "pushed" ? "restore" : "push", id: b.id });
      });
      acts.appendChild(a2);

      var a3 = document.createElement("button");
      a3.type = "button";
      a3.textContent = b.status === "done" ? "↩ Geri Al" : "✅ Tamamlandı";
      a3.addEventListener("click", function(){
        adjust({ action: "done", id: b.id });
      });
      acts.appendChild(a3);

      div.appendChild(acts);

      if (b.status === "done"){
        var metrics = document.createElement("div");
        metrics.className = "pmetrics";
        metrics.appendChild(metricInput("Soru", b.questions, function(v){ saveMetrics(b.id, "questions", v); }));
        metrics.appendChild(metricInput("Sayfa", b.pages, function(v){ saveMetrics(b.id, "pages", v); }));
        div.appendChild(metrics);
      }
    }

    return div;
  }

  function renderPlan(plan){
    var tl = $("timeline");
    tl.innerHTML = "";
    var fit = plan && plan.meta && plan.meta.fit;
    var fb = $("fit-banner");
    if (fit && fit.scaled){
      fb.hidden = false;
      fb.textContent = "⚠ " + fit.topic_count + " konu için en az " + fit.required_hours + " saat gerekli — bloklar ölçeklenerek tüm konular yerleştirildi.";
    } else {
      fb.hidden = true;
    }
    var enabled = !!(plan && plan.blocks && plan.blocks.length);
    $("shift15").disabled = !enabled;
    $("shift30").disabled = !enabled;
    lastPlan = plan ? plan.blocks : null;
    lastMeta = plan ? plan.meta : null;
    updateStats();
    timerState.remainingSeconds = 0;
    timerState.targetEndTs = 0;
    if (!plan){
      if (timerInt){ clearInterval(timerInt); timerInt = null; }
      var e = document.createElement("div");
      e.className = "empty";
      e.innerHTML = "<b>Henüz plan yok</b>Soldan konuları seç ve \u201c🚀 Planı Oluştur\u201d.";
      tl.appendChild(e);
      $("tl-note").textContent = "🔴60 · 🟡45 · 🟢30 dk bloklar · 10 dk mola.";
      return;
    }
    $("tl-note").textContent = plan.meta.note;
    if (plan.meta && plan.meta.school) renderSchool(plan.meta.school);
    renderAnchorId = null;
    var runningNow = plan.blocks.filter(function(b){ return b.type === "study" && b.active; });
    if (runningNow.length){
      renderAnchorId = runningNow[0].id;
      timerState.activeBlockId = runningNow[0].id;
      timerState.isRunning = true;
    } else {
      timerState.isRunning = false;
      var keepBlock = null;
      plan.blocks.forEach(function(b){
        if (b.type === "study" && b.id === timerState.activeBlockId && (b.elapsed || 0) > 0) keepBlock = b;
      });
      if (keepBlock){
        renderAnchorId = keepBlock.id;
        timerState.activeBlockId = keepBlock.id;
      } else {
        var firstPaused = null;
        plan.blocks.forEach(function(b){
          if (!firstPaused && b.type === "study" && (b.elapsed || 0) > 0) firstPaused = b;
        });
        renderAnchorId = firstPaused ? firstPaused.id : null;
        timerState.activeBlockId = renderAnchorId;
      }
    }
    plan.blocks.forEach(function(b){ tl.appendChild(blockEl(b)); });
    $("st-total").textContent = plan.stats.total_min;
    $("st-done").textContent = plan.stats.done_min;
    $("st-count").textContent = plan.stats.done_count + "/" + plan.blocks.filter(function(b){ return b.type === "study" && b.status !== "pushed"; }).length;
    startTimers();
    refreshStats();
  }

  function fmt(sec){
    sec = Math.max(0, Math.floor(sec));
    return String(Math.floor(sec / 60)).padStart(2, "0") + ":" + String(sec % 60).padStart(2, "0");
  }

  function blockWindow(b){
    var d = new Date();
    d.setHours(0, 0, 0, 0);
    var base = d.getTime();
    return { startTs: base + b.start * 60000, endTs: base + b.end * 60000 };
  }

  function blockElapsedTotal(b, nowSec){
    var el = b.elapsed || 0;
    if (b.active && b.started_at){
      el += Math.max(0, nowSec - b.started_at);
    }
    return el;
  }

  function blockSeconds(b){
    var mins = Math.max(1, (b.duration > 0) ? b.duration : (b.end - b.start));
    return mins * 60;
  }

  function parseTimeToMin(s){
    var p = s.split(":");
    return parseInt(p[0],10)*60 + parseInt(p[1],10);
  }

  function minToTimeStr(total){
    total = ((total % 1440) + 1440) % 1440;
    return String(Math.floor(total/60)).padStart(2,"0") + ":" + String(total%60).padStart(2,"0");
  }

  function updateDefaultText(){
    var span = document.querySelector(".win .t");
    if (span) span.textContent = "(varsayılan " + $("win-s").value + " - " + $("win-e").value + ")";
  }

  function syncPillFromTimes(){
    var sMin = parseTimeToMin($("win-s").value);
    var eMin = parseTimeToMin($("win-e").value);
    var diff = eMin - sMin;
    if (diff <= 0) diff += 1440;
    var matched = false;
    document.querySelectorAll("#dur-pills .pill[data-dur]").forEach(function(p){
      var d = parseInt(p.dataset.dur,10);
      if (d*60 === diff){ p.classList.add("active"); matched = true; }
      else p.classList.remove("active");
    });
    if (matched) duration = diff / 60;
    updateDefaultText();
  }

  function writeTimer(b, remaining){
    var ct = document.querySelector('.ctimer[data-bid="' + b.id + '"]');
    if (!ct) return;
    var text = fmt(remaining);
    if (ct.textContent !== text) ct.textContent = text;
    var fill = document.querySelector('.progress-fill[data-bid="' + b.id + '"]');
    if (fill){
      var pct = Math.min(100, (blockElapsedTotal(b, Math.floor(Date.now() / 1000)) / blockSeconds(b)) * 100);
      var wpct = pct.toFixed(1) + "%";
      if (fill.style.width !== wpct) fill.style.width = wpct;
    }
  }

  function tick(){
    var blocks = lastPlan || [];

    blocks.forEach(function(b){
      if (b.type === "study" && b.status === "pushed") return;

      var el = document.querySelector('.pblock[data-bid="' + b.id + '"]');
      var now = Date.now();
      var win = blockWindow(b);
      var wall;
      if (now < win.startTs) wall = "up";
      else if (now >= win.endTs) wall = "co";
      else wall = "ac";

      if (el){
        el.classList.remove("w-up", "w-ac", "w-co");
        el.classList.add("w-" + wall);
      }

      var chip = document.querySelector('.pstat[data-bid="' + b.id + '"]');
      if (chip && b.status !== "done"){
        chip.className = "pstat " + wall;
        chip.textContent = wall === "up" ? "🔜 Başlaması bekleniyor"
          : wall === "ac" ? "▶ Planlanan aralık aktif" : "✅ Planlanan süresi geçti";
      }
    });

    var running = null;
    blocks.forEach(function(b){
      if (b.type === "study" && b.active && !running) running = b;
    });

    if (running){
      var prevRemaining = timerState.remainingSeconds;
      if (timerState.activeBlockId !== running.id || timerState.targetEndTs === 0){
        var initialSeconds = blockSeconds(running);
        timerState.activeBlockId = running.id;
        timerState.isRunning = true;
        completionFired = false;
        timerState.remainingSeconds = Math.max(0, Math.round(initialSeconds - blockElapsedTotal(running, Math.floor(Date.now() / 1000))));
        timerState.targetEndTs = Date.now() + timerState.remainingSeconds * 1000;
      } else {
        timerState.isRunning = true;
        timerState.remainingSeconds = Math.max(0, Math.round((timerState.targetEndTs - Date.now()) / 1000));
      }
      writeTimer(running, timerState.remainingSeconds);
      if (zenActive && running.id === zenBlockId){
        var zcd = $("zen-countdown"); if (zcd) zcd.textContent = fmt(timerState.remainingSeconds);
        var zf = $("zen-fill"); if (zf){
          var tot = blockSeconds(running);
          var zp = tot ? ((tot - timerState.remainingSeconds) / tot) * 100 : 0;
          zf.style.width = Math.min(100, zp).toFixed(1) + "%";
        }
        var zs = $("zen-status"); if (zs && zs.textContent !== "Seans devam ediyor...") zs.textContent = "Seans devam ediyor...";
      }
      if (timerState.isRunning && prevRemaining > 0 && timerState.remainingSeconds <= 0){
        onTimerComplete(running);
      }
    } else {
      timerState.isRunning = false;
      timerState.targetEndTs = 0;
      completionFired = false;
      if (timerState.activeBlockId !== null){
        var anchorBlock = null;
        blocks.forEach(function(b){
          if (b.type === "study" && b.id === timerState.activeBlockId) anchorBlock = b;
        });
        if (anchorBlock){
          var pausedRemaining = Math.max(0, Math.round(blockSeconds(anchorBlock) - (anchorBlock.elapsed || 0)));
          timerState.remainingSeconds = pausedRemaining;
          writeTimer(anchorBlock, pausedRemaining);
        }
      }
    }
    updateStats();
  }

  function startTimers(){
    if (timerInt) clearInterval(timerInt);
    tick();
    timerInt = setInterval(tick, 1000);
  }

  function dayLabel(ts){
    var days = Math.floor((Date.now() / 1000 - ts) / 86400);
    if (days <= 0) return "bugün";
    if (days === 1) return "1 gün önce";
    return days + " gün önce";
  }

  function itemRow(w, buttons, tom){
    var row = document.createElement("div");
    row.className = "witem";
    var sub = document.createElement("span");
    sub.className = "ws";
    sub.textContent = w.subject;
    var t = document.createElement("span");
    t.className = "wt";
    t.textContent = (tom ? "⏩ " : "🔴 ") + w.topic;
    var d = document.createElement("span");
    d.className = "wd";
    d.textContent = (w.time ? w.time + " · " : "") + (tom ? "yarın için" : dayLabel(w.added));
    row.appendChild(sub);
    row.appendChild(t);
    row.appendChild(d);
    var meta = document.createElement("span");
    meta.className = "wmeta";
    buttons.forEach(function(btn){
      var b = document.createElement("button");
      b.type = "button";
      b.className = "btn-sm " + (btn.pln ? "btn-pln" : "");
      b.textContent = btn.label;
      b.addEventListener("click", btn.fn);
      meta.appendChild(b);
    });
    row.appendChild(meta);
    return row;
  }

  function renderDrawer(d){
    var weak = d.weak || [];
    var tomorrow = d.tomorrow || [];
    var box = $("weak-list");
    box.innerHTML = "";
    $("weak-count").textContent = weak.length;

    if (tomorrow.length){
      var sec = document.createElement("div");
      sec.className = "dr-section tom";
      var h = document.createElement("h3");
      h.innerHTML = "⏩ Yarına İtelendi <span class='n'>(" + tomorrow.length + ")</span>";
      sec.appendChild(h);
      tomorrow.forEach(function(w){
        sec.appendChild(itemRow(w, [
          { label: "Bugün Planla", pln: true, fn: function(){ injectTopic(w.subject, w.topic); } },
          { label: "Kaldır", fn: function(){
              fetch("/api/tomorrow", { method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ remove: true, subject: w.subject, topic: w.topic }) })
              .then(function(r){ return r.json(); }).then(function(dd){ if (dd.status === "success") fetchDrawer(); });
          } }
        ], true));
      });
      box.appendChild(sec);
    }

    if (weak.length){
      var sec2 = document.createElement("div");
      sec2.className = "dr-section";
      var h2 = document.createElement("h3");
      h2.innerHTML = "🔴 Zayıf Konular <span class='n'>(" + weak.length + ")</span>";
      sec2.appendChild(h2);
      weak.forEach(function(w){
        sec2.appendChild(itemRow(w, [
          { label: "Bugün Planla", pln: true, fn: function(){ injectTopic(w.subject, w.topic); } },
          { label: "Kaldır", fn: function(){
              fetch("/api/weak", { method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ remove: true, subject: w.subject, topic: w.topic }) })
              .then(function(r){ return r.json(); }).then(function(dd){ if (dd.status === "success") fetchDrawer(); });
          } }
        ], false));
      });
      box.appendChild(sec2);
    }

    if (!weak.length && !tomorrow.length){
      var e = document.createElement("div");
      e.className = "empty";
      e.innerHTML = "<b>Zayıf konu yok</b>Çalışırken bir konuda \u201c🔴 Zorlanıyorum\u201d seç veya bir bloğu ⏩ yarına itele.";
      box.appendChild(e);
    }
  }

  function fetchDrawer(){
    fetch("/api/drawer").then(function(r){ return r.json(); }).then(function(d){
      if (d.status === "success") renderDrawer(d);
    }).catch(function(){});
  }

  function fetchReviews(){
    fetch("/api/reviews").then(function(r){ return r.json(); }).then(function(d){
      if (d.status === "success" && d.reviews.length){
        var subjects = d.reviews.map(function(r){ return r.subject + " · " + r.topic; });
        $("rb-text").textContent = d.reviews.length + " Spaced Review bekliyor (" + subjects.join(", ") + ") — timeline'a ekle?";
        $("review-banner").classList.add("show");
      }
    }).catch(function(){});
  }

  function scheduleReviews(){
    fetch("/api/reviews/schedule", {method:"POST", headers:{"Content-Type":"application/json"}})
      .then(function(r){ return r.json(); }).then(function(d){
        if (d.status === "success"){
          $("review-banner").classList.remove("show");
          setMsg("✓ " + d.message, "ok");
          if (d.plan) renderPlan(d.plan);
        } else {
          setMsg(d.message || "Hata oluştu.", "err");
        }
      }).catch(function(){ setMsg("Bağlantı hatası.", "err"); });
  }

  function escHtml(s){
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }

  function fmtMinTotal(m){
    m = Math.max(0, Math.round(m || 0));
    if (m >= 60){
      var h = Math.floor(m / 60), r = m % 60;
      return r ? h + " s " + r + " dk" : h + " saat";
    }
    return m + " dk";
  }

  function metricInput(label, val, onCommit){
    var wrap = document.createElement("label");
    wrap.className = "metric";
    var span = document.createElement("span");
    span.textContent = "✓ " + label;
    var input = document.createElement("input");
    input.type = "number";
    input.min = "0";
    input.step = "1";
    input.setAttribute("inputmode", "numeric");
    input.placeholder = "0";
    if (val) input.value = val;
    var deb = null;
    function commit(){
      var v = parseInt(input.value, 10);
      if (isNaN(v) || v < 0) v = 0;
      onCommit(v);
    }
    input.addEventListener("input", function(){
      if (deb) clearTimeout(deb);
      deb = setTimeout(commit, 650);
    });
    input.addEventListener("change", commit);
    wrap.appendChild(span);
    wrap.appendChild(input);
    return wrap;
  }

  function saveMetrics(id, field, value){
    var payload = { id: id };
    payload[field] = value;
    fetch("/api/blocks/metrics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function(r){ return r.json(); }).then(function(d){
      if (d.status === "success"){
        setMsg("✓ Kaydedildi (" + field + ": " + value + ")", "ok");
        refreshStats();
      }
      else setMsg(d.message || "Hata oluştu.", "err");
    }).catch(function(){ setMsg("Bağlantı hatası.", "err"); });
  }

  function switchTab(pane){
    var tw = $("tab-wiz"), ts = $("tab-stat");
    if (tw) tw.classList.toggle("active", pane === "wiz");
    if (ts) ts.classList.toggle("active", pane === "stat");
    var an = $("analytics-panel");
    if (an){
      an.hidden = pane !== "stat";
      an.classList.toggle("show", pane === "stat");
      if (pane === "stat" && an.hidden === false) an.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    if (pane === "stat") fetchStats();
  }

  function renderSubjectBars(subjects){
    var box = $("st-subject-bars");
    box.innerHTML = "";
    if (!subjects || !subjects.length){
      box.innerHTML = "<div class='empty' style='padding:16px 10px;font-size:13px'><b>Veri yok</b>İlk bloğu tamamladığında dağılım burada görünür.</div>";
      return;
    }
    var max = 1;
    subjects.forEach(function(s){ if (s.minutes > max) max = s.minutes; });
    subjects.forEach(function(s){
      var row = document.createElement("div");
      row.className = "bar-row";
      var label = document.createElement("span");
      label.className = "bar-label";
      label.textContent = s.subject;
      var track = document.createElement("div");
      track.className = "bar-track";
      var fill = document.createElement("div");
      fill.className = "bar-fill";
      fill.style.width = Math.max(3, (s.minutes / max) * 100) + "%";
      track.appendChild(fill);
      var val = document.createElement("span");
      val.className = "bar-val";
      val.textContent = fmtMinTotal(s.minutes) + " · %" + s.percent;
      row.appendChild(label);
      row.appendChild(track);
      row.appendChild(val);
      box.appendChild(row);
    });
  }

  function renderDayBars(days){
    var box = $("st-day-bars");
    box.innerHTML = "";
    if (!days || !days.length) return;
    var max = 1;
    days.forEach(function(x){ if (x.minutes > max) max = x.minutes; });
    days.forEach(function(x){
      var col = document.createElement("div");
      col.className = "day-col";
      var fill = document.createElement("div");
      fill.className = "day-fill";
      fill.style.height = Math.max(3, (x.minutes / max) * 100) + "%";
      var mn = document.createElement("span");
      mn.className = "day-min";
      mn.textContent = x.minutes > 0 ? String(Math.round(x.minutes)) : "";
      var sub = null;
      if ((x.questions > 0) || (x.pages > 0)){
        sub = document.createElement("span");
        sub.className = "day-sub";
        sub.textContent = (x.questions > 0 ? "S" + x.questions : "") + (x.pages > 0 ? "·P" + x.pages : "");
      }
      var lb = document.createElement("span");
      lb.className = "day-lbl";
      lb.textContent = x.day;
      col.appendChild(fill);
      col.appendChild(mn);
      if (sub) col.appendChild(sub);
      col.appendChild(lb);
      box.appendChild(col);
    });
  }

  function refreshStats(){
    var an = $("analytics-panel");
    if (an && !an.hidden) fetchStats();
  }

  function fetchStats(){
    fetch("/api/stats").then(function(r){ return r.json(); }).then(function(d){
      if (d.status !== "success") return;
      $("st-today").textContent = fmtMinTotal(d.today.minutes);
      $("st-today-sub").textContent = d.today.done + " seans · " + d.today.questions + " soru";
      $("st-week").textContent = fmtMinTotal(d.week.minutes);
      $("st-week-sub").textContent = d.week.done + " seans · " + d.week.pages + " sayfa";
      $("st-qs").textContent = d.week.questions;
      $("st-qsub").textContent = d.week.pages + " okuma sayfası";
      renderSubjectBars(d.subjects);
      renderDayBars(d.days);
    }).catch(function(){});
  }

  function fetchOverdue(){
    fetch("/api/overdue").then(function(r){ return r.json(); }).then(function(d){
      if (d.status === "success" && d.count){
        var labels = d.overdue.map(function(o){ return o.subject + " · " + o.topic; });
        var shown = labels.slice(0,3).join(", ");
        var extra = d.count > 3 ? " ve " + (d.count - 3) + " tane daha" : "";
        $("cb-text").textContent = "⚠️ " + d.count + " gecikmiş konu var (" + shown + extra + "). Catch-Up Modu etkinleştir?";
        $("catchup-bar").classList.add("show");
      }
    }).catch(function(){});
  }

  function activateCatchUp(){
    fetch("/api/catchup", {method:"POST", headers:{"Content-Type":"application/json"}})
      .then(function(r){ return r.json(); }).then(function(d){
        if (d.status === "success"){
          $("catchup-bar").classList.remove("show");
          setMsg("✓ Catch-Up tamamlandı.", "ok");
          fetchDrawer();
          showCatchupModal(d.summary || {});
        } else {
          setMsg(d.message || "Hata oluştu.", "err");
        }
      }).catch(function(){ setMsg("Bağlantı hatası.", "err"); });
  }

  function showCatchupModal(s){
    var lines = [];
    if (s.note) lines.push("• " + s.note);
    if (s.days && Object.keys(s.days).length){
      var dstr = Object.keys(s.days).map(function(d){ return s.days[d].label; }).join(" / ");
      lines.push("• " + (s.missed || 0) + " gecikmiş konu sonraki 3 güne eşit dağıtıldı: " + dstr);
      Object.keys(s.days).forEach(function(d){
        s.days[d].topics.forEach(function(t){
          lines.push("   - " + t + " · " + s.days[d].label);
        });
      });
    }
    if (!lines.length) lines.push("• Gecikmiş konu bulunamadı.");
    $("m-list").innerHTML = lines.map(function(l){ return "<li>" + escHtml(l) + "</li>"; }).join("");
    $("m-sub").textContent = "Değişiklik özeti — kuyruğa eklenenler sonraki günler açıldığında plana \"⏰ Rescheduled\" etiketiyle dahil edilir.";
    $("overlay").classList.add("show");
  }

  function extendTimer(block){
    completionFired = false;
    if (timerState.isRunning){
      timerState.targetEndTs += 300 * 1000;
      timerState.remainingSeconds = Math.max(0, Math.floor((timerState.targetEndTs - Date.now()) / 1000));
    } else {
      timerState.remainingSeconds += 300;
      timerState.targetEndTs = 0;
    }
    block.duration = Math.min((block.duration || 5) + 5, (block.origDuration || block.duration || 5) + 60);
    writeTimer(block, timerState.remainingSeconds);
    updateStats();
    adjust({ action: "extend", id: block.id });
  }

  function finishEarly(block){
    adjust({ action: "done", id: block.id }, function(){
      var blocks = lastPlan || [];
      var idx = -1;
      blocks.forEach(function(x, i){ if (x.id === block.id) idx = i; });
      var nxt = null;
      for (var i = idx + 1; i < blocks.length; i++){
        if (blocks[i].type === "study" && blocks[i].status !== "pushed"){ nxt = blocks[i]; break; }
      }
      if (nxt) adjust({ action: "start", id: nxt.id });
    });
  }

  function onTimerComplete(block){
    if (completionFired) return;
    completionFired = true;
    playChime();
    notifyComplete(block);
    if (zenActive){
      adjust({ action: "done", id: block.id }, function(){
        fetchGame();
        showZenSplash("Seans Tamamlandı!", "🏗 Yeni modül inşa edildi. XP kazandın!", true);
      });
    } else {
      adjust({ action: "stop", id: block.id });
    }
  }

  function adjust(payload, after){
    fetch("/api/blocks/adjust", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function(r){ return r.json(); }).then(function(d){
      if (d.status !== "success"){ setMsg(d.message || "Hata oluştu.", "err"); return; }
      if (d.plan) renderPlan(d.plan);
      if (d.message) setMsg(d.message, "ok");
      if (d.hasOwnProperty("weak") || d.hasOwnProperty("tomorrow")) renderDrawer(d);
      else fetchDrawer();
      fetchGame();
      if (after) after(d);
    }).catch(function(){ setMsg("Bağlantı hatası.", "err"); });
  }

  $("shift15").addEventListener("click", function(){ adjust({ action: "shift", offset: 15 }); });
  $("shift30").addEventListener("click", function(){ adjust({ action: "shift", offset: 30 }); });
  var _rb = $("rb-add"); if (_rb) _rb.addEventListener("click", function(){ scheduleReviews(); });
  var _cb = $("cb-btn"); if (_cb) _cb.addEventListener("click", function(){ activateCatchUp(); });
  var _overlay = $("overlay");
  var _mclose = $("m-close");
  if (_mclose) _mclose.addEventListener("click", function(){ if (_overlay) _overlay.classList.remove("show"); });
  if (_overlay) _overlay.addEventListener("click", function(e){ if (e.target === _overlay) _overlay.classList.remove("show"); });
  var _tabW = $("tab-wiz"), _tabS = $("tab-stat");
  if (_tabW) _tabW.addEventListener("click", function(){ switchTab("wiz"); });
  if (_tabS) _tabS.addEventListener("click", function(){ switchTab("stat"); });
  var _sc = $("stats-collapse");
  if (_sc) _sc.addEventListener("click", function(){ switchTab("wiz"); });
  var _zlofi = $("zen-lofi");
  if (_zlofi) _zlofi.addEventListener("click", function(){
    var on = _zlofi.classList.toggle("on");
    if (on) startLoFi(); else stopLoFi();
  });
  var _zspace = $("zen-space");
  if (_zspace) _zspace.addEventListener("click", function(){
    var on = _zspace.classList.toggle("on");
    if (on) startSpace(); else stopSpace();
  });
  var _zab = $("zen-abandon");
  if (_zab) _zab.addEventListener("click", function(){
    if (!zenActive || !zenBlockId) return;
    var blocks = lastPlan || [];
    var blk = null;
    blocks.forEach(function(x){ if (x.id === zenBlockId) blk = x; });
    if (blk){ zenAbandonPending = blk; openZenConfirm(); }
  });
  var _zco = $("zen-confirm-ok");
  if (_zco) _zco.addEventListener("click", function(){ doAbandonZen(); });
  var _zcc = $("zen-confirm-cancel");
  if (_zcc) _zcc.addEventListener("click", function(){ closeZenConfirm(); });
  var _zok = $("zen-btn-ok");
  if (_zok) _zok.addEventListener("click", function(){
    $("zen-splash").hidden = true;
  });
  var _rst = $("stats-reset");
  if (_rst) _rst.addEventListener("click", function(){
    var ok = typeof window.confirm === "function" && window.confirm(
      "Tüm istatistik verileri silinsin mi?\nSoru, sayfa ve çalışma süresi kayıtları sıfırlanır; timeline etkilenmez."
    );
    if (!ok) return;
    fetch("/api/stats/reset", { method: "POST" }).then(function(r){ return r.json(); }).then(function(d){
      if (d.status === "success"){
        setMsg("✓ İstatistikler sıfırlandı.", "ok");
        fetch("/api/plan").then(function(r){ return r.json(); }).then(function(p){
          if (p.status === "success") renderPlan(p.plan);
          refreshStats();
        }).catch(function(){ refreshStats(); });
      }
      else setMsg(d.message || "Hata oluştu.", "err");
    }).catch(function(){ setMsg("Bağlantı hatası.", "err"); });
  });

  function postBlocks(payload){
    fetch("/api/blocks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function(r){ return r.json(); }).then(function(d){
      if (d.status !== "success"){
        if (payload.clear) renderPlan(null);
        return;
      }
      if (payload.clear) renderPlan(null);
      else renderPlan(d.plan);
    }).catch(function(){ setMsg("Bağlantı hatası.", "err"); });
  }

  function submitPlan(append){
    if (!selected.length){ setMsg("Önce en az bir konu seç.", "err"); return; }
    var start = $("win-s").value, end = $("win-e").value;
    var s = parseInt(start.split(":")[0], 10) * 60 + parseInt(start.split(":")[1], 10);
    var e = parseInt(end.split(":")[0], 10) * 60 + parseInt(end.split(":")[1], 10);
    if (e <= s){ setMsg("Bitiş saati başlangıçtan sonra olmalı.", "err"); return; }
    setMsg("Plan oluşturuluyor…");
    fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topics: selected,
        start: start,
        end: end,
        duration_h: duration,
        mode: mode,
        criterion: criterion,
        append: !!append
      })
    }).then(function(r){ return r.json(); }).then(function(d){
      if (d.status !== "success"){ setMsg(d.message || "Hata oluştu.", "err"); return; }
      setMsg("✓ Plan hazır · " + d.plan.created, "ok");
      renderPlan(d.plan);
      renderDrawer(d);
    }).catch(function(){ setMsg("Bağlantı hatası.", "err"); });
  }

  $("go").addEventListener("click", function(){ submitPlan(false); });

  $("reset").addEventListener("click", function(){
    selected.forEach(function(it){ var p = findPill(it.subject, it.topic); if (p) p.classList.remove("active"); });
    selected = [];
    rebuildChips();
    $("win-s").value = "17:00";
    $("win-e").value = "19:00";
    duration = 2;
    syncPillFromTimes();
    mode = "practice";
    document.querySelectorAll("#mode-pills .pill").forEach(function(p){ p.classList.toggle("active", p.dataset.mode === mode); });
    criterion = "A";
    document.querySelectorAll("#cri-pills .pill").forEach(function(p){ p.classList.toggle("active", p.dataset.cri === criterion); });
    updateDefaultText();
    postBlocks({ clear: true });
    setMsg("Hepsi sıfırlandı · varsayılanlar geri yüklendi (17:00 - 19:00).", "ok");
  });

  document.body.addEventListener("click", function(){ ensureAudio(); });
  fetch("/api/plan").then(function(r){ return r.json(); }).then(function(d){
    if (d.status === "success") renderPlan(d.plan);
  }).catch(function(){});
  fetchDrawer();
  fetchReviews();
  fetchOverdue();
  fetchGame();
  fetchSchool();
  rebuildChips();
})();
