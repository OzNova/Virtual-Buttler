//! Butler Tauri shell (Phase 5 scaffold, local-only).
//! Tray + global shortcut (Cmd/Ctrl+Shift+Space) focusing the HUD window.
//! Backend stays Python FastAPI on 127.0.0.1:8000; Tauri only hosts the HUD.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager,
};

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .setup(|app| {
            let quit = MenuItem::with_id(app, "quit", "Quit Butler", true, None::<&str>)?;
            let show = MenuItem::with_id(app, "show", "Show HUD", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            let _tray = TrayIconBuilder::with_id("butler-tray")
                .tooltip("Butler (local-only)")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "quit" => app.exit(0),
                    "show" => {
                        if let Some(win) = app.get_webview_window("main") {
                            let _ = win.show();
                            let _ = win.set_focus();
                        }
                    }
                    _ => {}
                })
                .build(app)?;
            Ok(())
        })
        .on_window_event(|win, ev| {
            // Hide instead of closing so the tray keeps Butler alive.
            if let tauri::WindowEvent::CloseRequested { api, .. } = ev {
                let _ = win.hide();
                api.prevent_close();
            }
        })
        .run(tauri::generate_context!())
        .expect("Butler Tauri shell failed to start");
}
