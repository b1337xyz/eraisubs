#!/usr/bin/env python3
from pathlib import Path
from bs4 import BeautifulSoup as BS
from argparse import ArgumentParser
from datetime import datetime
from urllib.parse import quote, unquote
from http.cookiejar import MozillaCookieJar
import subprocess as sp
import requests
import sqlite3 as sql
import json
import re


ROOT = Path(__file__).resolve().parent
FAV_FILE = ROOT / 'erai.txt'
CONFIG = ROOT / 'config.json'


def parse_arguments():
    parser = ArgumentParser()
    parser.add_argument('-d', dest='dir', default=Path.cwd(), metavar='PATH',
                      help='Path to save downloaded files')
    parser.add_argument('-f', dest='favorites', action='store_true',
                      help='List favorites')
    parser.add_argument('-r', dest='remove', action='store_true',
                      help='Remove entry from favorites')
    parser.add_argument('-l', dest='latest', action='store_true',
                      help='List the latest releases')
    parser.add_argument('-y', dest='year', type=int, metavar='YEAR',
                      help='Start from year')
    parser.add_argument('-C', dest='cookie_file', metavar='FILE',
                      help='Path to cookie file')
    parser.add_argument('-c', dest='cookie', metavar='COOKIE',
                      help='Cookie string')
    parser.add_argument('-v', dest='verbose', action='store_true',
                      help='Enable verbose mode')
    parser.add_argument('argv', nargs='*')
    return parser.parse_args()


def select(args):
    args = [f'{i}/{v}' for i, v in enumerate(args)]
    fzf_args = [
        '-m',
        '-d', '/',
        '--with-nth', '2..',
        '--height', '20',
        '--cycle',
        '--tac',
        '--reverse',
        '--keep-right',
        '--bind', f'ctrl-f:execute(echo {{}} >> {FAV_FILE})',
        '--bind', 'ctrl-a:toggle-all',
        '--header', 'ctrl-f add to favorites | ctrl-a select-all'
    ]
    p = sp.Popen(
        ['fzf'] + fzf_args,
        stdin=sp.PIPE, stdout=sp.PIPE,
        universal_newlines=True
    )
    sel, _ = p.communicate('\n'.join(args))
    return [int(i.split('/')[0]) for i in sel.split('\n') if i]


def load_cookies_from_chromium(cookie_file):
    # TODO: only tested with qutebrowser
    con = sql.connect(f'file:{cookie_file}?nolock=1', uri=True)
    cur = con.cursor()
    cur.execute("""
        SELECT host_key, name, value FROM cookies
        WHERE host_key LIKE '%erai%';
    """)
    return cur.fetchall()


def load_cookies_from_cookie_jar(session, cookie_file):
    cj = MozillaCookieJar(cookie_file)
    cj.load(ignore_discard=True, ignore_expires=True)
    return cj


def create_session(cookie_string=None, cookie_file=None, **kw):
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0'})

    # TODO: improve this...
    if cookie_file:
        try:
            cookies = load_cookies_from_chromium(cookie_file)
            for domain, name, value in cookies:
                session.cookies.set(name, value, domain=domain)
        except Exception:
            session.cookies = load_cookies_from_cookie_jar(cookie_file)
    elif cookie_string:
        for cookie in cookie_string.split(';'):
            name, value = map(str.strip, cookie.split('='))
            session.cookies.set(name, value, domain='www.erai-raws.info')
    else:
        print('Cookies are required!')
        exit(1)

    return session


def download(session, url, path=None):
    r = session.get(url, stream=True)
    filename = unquote(url.split('/')[-1])
    if path:
        path /= filename
    else:
        path = filename

    with open(path, 'wb') as f:
        f.write(r.content)
    print(path, 'saved')


def get_soup(session, url):
    # TODO: check for errors, don't use assert for this.
    r = session.get(url)
    assert r.ok
    return BS(r.text, 'html.parser')


def get_files(soup):
    try:
        return [
            a['href']
            for a in soup.find(id='directory-listing').find_all('a', href=True)
            if not a['href'].endswith('/subs/')
        ]
    except AttributeError:
        print('Nothing found, check if you are logged in.')
        exit(1)


def load_favorites():
    with open(FAV_FILE, 'r') as f:
        return [i.strip() for i in f.readlines() if i]


def load_config():
    try:
        with open(CONFIG, 'r') as f:
            return json.load(f)
    except Exception:
        return {
            'cookie_file': None,
            'cookie_string': None,
        }


def main(opts, args):
    dl_dir = Path(opts.dir)
    config = load_config()
    base_url = 'https://www.erai-raws.info/subs/'
    url = f'{base_url}?dir=Sub'
    is_file = re.compile(r'.*\.(zip|rar|7z|vtt|sub|ass|srt)$', re.IGNORECASE)

    if opts.favorites:
        favorites = load_favorites()
        sel = select(favorites)
        if not sel:
            return
        url = f'{base_url}?dir={quote(favorites[sel[0]])}'

    elif opts.remove:
        favorites = load_favorites()
        sel = select(favorites)
        for i in sel:
            del favorites[i]
        with open(FAV_FILE, 'w') as f:
            f.write('\n'.join(favorites))
        return

    elif opts.year:
        url = f'{base_url}?dir=Sub/{opts.year}'
    elif opts.latest:
        q = (datetime.now().month - 1) // 3
        s = ['Winter', 'Spring', 'Summer', 'Fall'][q]
        y = datetime.now().year
        url = f'{base_url}?dir=Sub/{y}/{s}'

    if opts.cookie_file:
        config['cookie_file'] = opts.cookie_file
    if opts.cookie:
        config['cookie_string'] = opts.cookie
    if opts.cookie_file or opts.cookie:
        with open(CONFIG, 'w') as f:
            json.dump(config, f)

    session = create_session(**config)

    dirs = {}
    while True:
        if opts.verbose:
            print(url)

        if url not in dirs:
            soup = get_soup(session, url)
            dirs[url] = get_files(soup)

        files = dirs[url]
        sel = select([unquote(i.split('dir=')[-1]) for i in files])
        if not sel:
            break

        for i in sel:
            href = files[i]
            if is_file.match(href):
                download(session, f'{base_url}{href}', dl_dir)
            else:
                url = href if href.startswith('http') else f'{base_url}{href}'


if __name__ == '__main__':
    opts = parse_arguments()
    main(opts, opts.argv)
