/* Spotify Dock — panel indicator + dropdown controls.
 * Talks to the spotify-dock daemon (127.0.0.1:47555).
 * Icon is visible ONLY while a playback session is active on the account. */

import GObject from 'gi://GObject';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import Pango from 'gi://Pango';
import Soup from 'gi://Soup';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const DAEMON_BASE = 'http://127.0.0.1:47555';
const POLL_SECONDS = 1;
const ART_SIZE = 64;

export default class SpotifyDockExtension extends Extension {
    enable() {
        this._session = new Soup.Session();
        this._lastArtKey = null;
        this._lastTrack = null;
        this._lastArtist = null;
        this._lastPlaying = null;
        this._lastControl = null;

        // ---- panel button (right side, next to the other app indicators) ----
        this._button = new PanelMenu.Button(0.0, 'Spotify Dock', false);
        this._panelIcon = new St.Icon({
            gicon: Gio.FileIcon.new(Gio.File.new_for_path(`${this.path}/icons/spotify.svg`)),
            icon_size: 18,
            style_class: 'sd-panel-icon',
        });
        this._button.add_child(this._panelIcon);
        this._button.visible = false;

        this._buildMenu();

        Main.panel.addToStatusArea('spotify-dock', this._button, 0, 'right');

        this._pollId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, POLL_SECONDS, () => {
            this._poll();
            return GLib.SOURCE_CONTINUE;
        });
        this._poll();
    }

    disable() {
        if (this._pollId) {
            GLib.source_remove(this._pollId);
            this._pollId = null;
        }
        if (this._button) {
            this._button.destroy();
            this._button = null;
        }
    }

    // ---------------------------------------------------------------- menu --
    _buildMenu() {
        const item = new PopupMenu.PopupBaseMenuItem({reactive: false});
        const box = new St.BoxLayout({style_class: 'sd-content'});

        this._artBox = new St.Bin({width: ART_SIZE, height: ART_SIZE, style_class: 'sd-art'});

        const info = new St.BoxLayout({vertical: true, style_class: 'sd-info'});
        this._trackLabel = new St.Label({style_class: 'sd-track', text: ''});
        this._trackLabel.clutter_text.ellipsize = Pango.EllipsizeMode.END;
        this._artistLabel = new St.Label({style_class: 'sd-artist', text: ''});
        this._artistLabel.clutter_text.ellipsize = Pango.EllipsizeMode.END;

        this._btnPrev = this._makeButton('media-skip-backward-symbolic',
            () => this._control('previous'));
        this._btnPlay = this._makeButton('media-playback-start-symbolic',
            () => this._control('playpause'));
        this._playIcon = this._btnPlay.get_child();
        this._btnNext = this._makeButton('media-skip-forward-symbolic',
            () => this._control('next'));

        const buttons = new St.BoxLayout({style_class: 'sd-btns'});
        buttons.add_child(this._btnPrev);
        buttons.add_child(this._btnPlay);
        buttons.add_child(this._btnNext);

        this._noteLabel = new St.Label({
            style_class: 'sd-note',
            text: '',
            visible: false,
        });

        info.add_child(this._trackLabel);
        info.add_child(this._artistLabel);
        info.add_child(buttons);
        info.add_child(this._noteLabel);

        box.add_child(this._artBox);
        box.add_child(info);
        item.add_child(box);
        this._button.menu.addMenuItem(item);
    }

    _makeButton(iconName, cb) {
        const btn = new St.Button({style_class: 'sd-btn'});
        btn.add_child(new St.Icon({icon_name: iconName, icon_size: 20}));
        btn.connect('clicked', cb);
        return btn;
    }

    // ---------------------------------------------------------------- poll --
    _poll() {
        this._fetchJson('/state', (err, state) => {
            if (err || !state || !state.ok) {
                this._setActive(false);
                return;
            }
            this._setActive(state.session_active === true);
            if (!state.session_active)
                return;

            // track / artist
            const track = state.track || '';
            const artist = state.artist || '';
            if (track !== this._lastTrack) {
                this._lastTrack = track;
                this._trackLabel.text = track;
            }
            if (artist !== this._lastArtist) {
                this._lastArtist = artist;
                this._artistLabel.text = artist;
            }

            // play/pause icon
            const playing = state.playing === true;
            if (playing !== this._lastPlaying) {
                this._lastPlaying = playing;
                this._playIcon.icon_name = playing
                    ? 'media-playback-pause-symbolic'
                    : 'media-playback-start-symbolic';
            }

            // album art (only reload when the track/image changed)
            if (state.art_key && state.art_key !== this._lastArtKey && state.art_path) {
                this._lastArtKey = state.art_key;
                this._loadArt(state.art_path);
            }

            // control availability
            const canControl = state.control === 'local' || state.control === 'remote';
            if (canControl !== this._lastControl) {
                this._lastControl = canControl;
                this._btnPrev.sensitive = canControl;
                this._btnPlay.sensitive = canControl;
                this._btnNext.sensitive = canControl;
            }
            const premiumNote = state.control_reason === 'premium_required';
            if (premiumNote !== this._noteLabel.visible) {
                this._noteLabel.visible = premiumNote;
                this._noteLabel.text = premiumNote
                    ? 'Remote control needs Spotify Premium'
                    : '';
            }
        });
    }

    _setActive(active) {
        if (this._button.visible !== active)
            this._button.visible = active;
        if (!active && this._button.menu.isOpen)
            this._button.menu.close();
    }

    _loadArt(path) {
        try {
            const file = Gio.File.new_for_path(path);
            const texture = St.TextureCache.get_default().load_file_sync(file, ART_SIZE, ART_SIZE);
            this._artBox.set_child(texture);
        } catch (e) {
            log(`spotify-dock: art load failed: ${e}`);
        }
    }

    _control(action) {
        if (action === 'playpause')
            action = this._lastPlaying ? 'pause' : 'play';
        const msg = Soup.Message.new('POST', `${DAEMON_BASE}/control`);
        msg.set_request_body_from_bytes(
            'application/json',
            new GLib.Bytes(JSON.stringify({action})));
        this._session.send_and_read_async(
            msg, GLib.PRIORITY_DEFAULT, null,
            (sess, res) => {
                try { sess.send_and_read_finish(res); } catch (e) { /* ignore */ }
            });
    }

    _fetchJson(path, cb) {
        const msg = Soup.Message.new('GET', DAEMON_BASE + path);
        this._session.send_and_read_async(
            msg, GLib.PRIORITY_DEFAULT, null,
            (sess, res) => {
                let state = null;
                try {
                    const bytes = sess.send_and_read_finish(res);
                    state = JSON.parse(new TextDecoder().decode(bytes.get_data()));
                } catch (e) {
                    cb(e, null);
                    return;
                }
                cb(null, state);
            });
    }
}
