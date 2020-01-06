#!/usr/bin/env python3
import datetime
import feedgen.feed
import html
import json
import logging
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
)

token = os.environ['GITHUB_PERSONAL_ACCESS_TOKEN']
owner, repo = os.environ['GITHUB_REPOSITORY'].split('/')
feed_url = f'https://{owner}.github.io/{repo}/atom.xml'
hub_url = 'https://pubsubhubbub.appspot.com/'

ssl_ctx = ssl.SSLContext()
ssl_ctx.load_default_certs()

def get(url):
    req = urllib.request.Request(
        url=url,
        headers={'User-Agent': 'Googlebot/2.1 (+http://www.google.com/bot.html)'},
    )
    with urllib.request.urlopen(req, context=ssl_ctx) as rsp:
        return rsp.read().decode('utf-8')

feed = feedgen.feed.FeedGenerator()
feed.id('urn:uuid:18019db5-cd10-4a0a-b32c-bb060bf1b2fe')
feed.link(rel='self', href=feed_url)
feed.link(rel='hub', href=hub_url)
feed.logo('https://xlab.tencent.com/cn/wp-content/themes/twentysixteen/images/small_logo_144.png')
feed.title('每日安全动态推送')
feed.author({'name': '腾讯安全玄武实验室', 'uri': 'https://xlab.tencent.com/'})
feed.language('zh-CN')

try:
    with open('gh-pages/timestamp.txt') as f:
        timestamp = datetime.datetime.fromisoformat(f.read())
except Exception:
    timestamp = datetime.datetime.fromtimestamp(0, datetime.timezone.utc)

logging.info('fetching article list')
articles = []
new_article_available = False
CST = datetime.timezone(datetime.timedelta(hours=8))
for match in re.finditer(r'<a target="_blank" href="([^"]+)" class="W_autocut S_txt1">\s*(.*?)</a>\s*</div>\s*</div>\s*<div class="subinfo_box">\s*<span class="subinfo S_txt2">(\d{4,}) 年 (\d{2}) 月 (\d{2}) 日 (\d{2}):(\d{2})</span>', get('https://weibo.com/p/1006065582522936/wenzhang')):
    uri, title, *publish_time = match.groups()
    uri = html.unescape(uri)
    if uri.endswith('&mod=zwenzhang'):
        uri = uri[:-14]
    assert uri.startswith('/')
    url = f'https://weibo.com{uri}'
    title = html.unescape(title)
    publish_time = datetime.datetime(*(int(s) for s in publish_time), tzinfo=CST)
    articles.append((url, title, publish_time))
    if publish_time > timestamp:
        new_article_available = True
        timestamp = publish_time

if not new_article_available:
    logging.info('new articles not found')
    sys.exit(0)

for url, title, publish_time in articles:
    logging.info('fetching article %s', title)
    article = get(url)
    items = re.search(r'(?s)<div class="WB_editor_iframe_new" node-type="contentBody" style="visibility: hidden">\s*(.*?)<p img-box="img-box" class="picbox">', article).group(1).split('\n<ul><br></ul>\n')

    for idx, item in enumerate(items):
        if '查看或搜索历史推送内容请访问' in item:
            continue
        title, link, content = re.fullmatch(r'<p align="justify">(.*?):<a href="([^"]*)"><br>.*?</a></p>\n<p align="justify">・\xa0(.*?)\xa0–\xa0<a href="https://sec\.today/user/[-0-9a-f]+/pushes/">.*?</a></p>', item).groups()
        title = html.unescape(title).replace('<i>', '').replace('</i>', '')
        content = html.unescape(content)
        entry = feed.add_entry(order='append')
        entry.id(f'{url}#{idx}')
        entry.updated(publish_time)
        entry.title(title)
        entry.link(href=link)
        entry.content(content, type='html')

with open('gh-pages/atom.xml', 'wb') as f:
    f.write(feed.atom_str(pretty=True))
with open('gh-pages/timestamp.txt', 'w') as f:
    f.write(timestamp.isoformat(timespec='minutes'))

subprocess.check_call(['.github/commit.sh'])

logging.info('deploy GitHub Pages')
req = urllib.request.Request(
    f'https://api.github.com/repos/{owner}/{repo}/pages/builds',
    method='POST',
    headers={
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
    },
)
with urllib.request.urlopen(req, context=ssl_ctx) as rsp:
    body = json.loads(rsp.read().decode())
status = body['status']

req.method = 'GET'
req.full_url = f'https://api.github.com/repos/{owner}/{repo}/pages'
while status not in ('built', 'errored'):
    time.sleep(5)
    with urllib.request.urlopen(req, context=ssl_ctx) as rsp:
        body = json.loads(rsp.read().decode())
    status = body['status']
assert status == 'built', f'GitHub Pages build failed'

logging.info('notify WebSub hub')
req = urllib.request.Request(
    hub_url,
    data=urllib.parse.urlencode({
        'hub.mode': 'publish',
        'hub.url': feed_url,
    }).encode(),
)
with urllib.request.urlopen(req, context=ssl_ctx) as rsp:
    pass
