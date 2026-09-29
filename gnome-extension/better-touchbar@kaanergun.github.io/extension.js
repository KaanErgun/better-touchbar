// Exports the focused app on the session bus for better-touchbar's session helper:
//   org.gnome.Shell /org/gnome/Shell/Extensions/TouchBar org.gnome.Shell.Extensions.TouchBar
//   GetFocus() -> (app id, WM_CLASS)      signal FocusChanged(app id, WM_CLASS)
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const IFACE = `
<node>
  <interface name="org.gnome.Shell.Extensions.TouchBar">
    <method name="GetFocus">
      <arg type="s" direction="out" name="app"/>
      <arg type="s" direction="out" name="wm_class"/>
    </method>
    <signal name="FocusChanged">
      <arg type="s" name="app"/>
      <arg type="s" name="wm_class"/>
    </signal>
  </interface>
</node>`;

export default class TouchBarFocus extends Extension {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, '/org/gnome/Shell/Extensions/TouchBar');
        this._focusId = global.display.connect('notify::focus-window', () => {
            this._dbus.emit_signal('FocusChanged', new GLib.Variant('(ss)', this._focus()));
        });
    }

    disable() {
        global.display.disconnect(this._focusId);
        this._dbus.unexport();
        this._dbus = null;
    }

    _focus() {
        const win = global.display.focus_window;
        if (!win)
            return ['', ''];
        const app = Shell.WindowTracker.get_default().get_window_app(win);
        return [app?.get_id() ?? '', win.get_wm_class() ?? ''];
    }

    GetFocus() {
        return this._focus();
    }
}
