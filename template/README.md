# template/

The design of the site: how every page looks and behaves.

- `layout.html`: the frame shared by every page (header, navigation, footer).
- `style.css`: all colors, type and spacing. Light and dark follow the device.
- `app.js`: the small script behind the show/hide switches, Sources and Settings pages, and the "new since your last visit" tags. Settings live only in the reader's browser.
- `chat.html` and `chat.js`: the Ask page. The script talks only to the helper on this computer (`chat_server.py`) and inserts everything it receives as text, never as HTML.
- `settings.html` and `fork.html`: the plain-content pages.

`build.py` fills these in with the news and writes the finished pages to `site/`. To change how the site looks, edit
`style.css` and run `./run.sh`. To change *what* appears, edit `config/sources.toml`.
