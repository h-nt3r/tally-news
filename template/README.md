# template/

The design of the site: how every page looks and behaves.

- `layout.html`: the frame shared by every page (header, navigation, footer).
- `style.css`: all colors, type and spacing. Light and dark follow the device.
- `app.js`: the small script behind the show/hide switches, Sources and Settings pages, and the "new since your last visit" tags. Settings live only in the reader's browser.
- `settings.html` and `fork.html`: the plain-content pages.

`build.py` fills these in with the news and writes the finished pages to `site/`. To change how the site looks, edit
`style.css` and run `./run.sh`. To change *what* appears, edit `config/sources.toml`.
