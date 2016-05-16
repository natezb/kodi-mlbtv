# -*- coding: utf-8 -*-
# Copyright 2016 Nate Bogdanowicz
import sys
import os
import os.path
import json
import urllib
import cookielib
import logging as log
from collections import defaultdict
import requests
from BeautifulSoup import BeautifulStoneSoup

TEAM_CODES = {
    '109': ('Arizona Diamondbacks', 'ari'),
    '144': ('Atlanta Braves', 'atl'),
    '110': ('Baltimore Orioles', 'bal'),
    '111': ('Boston Red Sox', 'bos'),
    '112': ('Chicago Cubs', 'chc'),
    '145': ('Chicago White Sox', 'cws'),
    '113': ('Cincinnati Reds', 'cin'),
    '114': ('Cleveland Indians', 'cle'),
    '115': ('Colorado Rockies', 'col'),
    '116': ('Detroit Tigers', 'det'),
    '146': ('Florida Marlins', 'mia'),
    '117': ('Houston Astros', 'hou'),
    '118': ('Kansas City Royals', 'kc'),
    '108': ('Los Angeles Angels', 'ana'),
    '119': ('Los Angeles Dodgers', 'la'),
    '158': ('Milwaukee Brewers', 'mil'),
    '142': ('Minnesota Twins', 'min'),
    '121': ('New York Mets', 'nym'),
    '147': ('New York Yankees', 'nyy'),
    '133': ('Oakland Athletics', 'oak'),
    '143': ('Philadelphia Phillies', 'phi'),
    '134': ('Pittsburgh Pirates', 'pit'),
    '135': ('San Diego Padres', 'sd'),
    '137': ('San Francisco Giants', 'sf'),
    '136': ('Seattle Mariners', 'sea'),
    '138': ('St Louis Cardinals', 'stl'),
    '139': ('Tampa Bay Rays', 'tb'),
    '140': ('Texas Rangers', 'tex'),
    '141': ('Toronto Blue Jays', 'tor'),
    '120': ('Washington Nationals', 'was')
}

SOAP_CODES = {
    "1": "OK",
    "-1000": "Requested Media Not Found",
    "-1500": "Other Undocumented Error",
    "-2000": "Authentication Error",
    "-2500": "Blackout Error",
    "-3000": "Identity Error",
    "-3500": "Sign-on Restriction Error",
    "-4000": "System Error",
}


def get_profile_dir():
    try:
        import xbmc
        import xbmcaddon
        addon = xbmcaddon.Addon()
        log.info(str(addon.getAddonInfo('path')))
        return (xbmc.translatePath(addon.getAddonInfo('profile')),
                xbmc.translatePath(addon.getAddonInfo('path')))
    except ImportError:
        return '.', '.'


def load_settings():
    settings = {}
    try:
        import xbmcplugin
        handle = int(sys.argv[1])
    except ImportError:
        return settings

    for key in ('email', 'password', 'debug', 'bitrate'):
        settings[key] = xbmcplugin.getSetting(handle, key)

    teams = []
    for code in TEAM_CODES:
        if xbmcplugin.getSetting(handle, code) == 'true':
            teams.append(code)
    settings['fav_team_ids'] = teams

    return settings


profile_dir, addon_dir = get_profile_dir()
settings = load_settings()
cookie_path = os.path.join(profile_dir, 'cookie_file')
cookie_jar = cookielib.LWPCookieJar(cookie_path)
if os.path.exists(cookie_path):
    cookie_jar.load()

if not os.path.exists(profile_dir):
    os.makedirs(profile_dir)

DEFAULT_HEADERS = {
    'User-agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:19.0) Gecko/20100101 Firefox/19.0'
}
sess = requests.Session()
sess.cookies = cookie_jar
sess.headers.update(DEFAULT_HEADERS)


def log_cookies(message="Cookies:"):
    lines = [message]
    for cookie in cookie_jar:
        lines.append("  {}: {}".format(cookie.name, cookie.value))
    log.info("\n".join(lines))


def get_games(date):
    url = date.strftime('http://mlb.mlb.com/gdcross/components/game/mlb/year_%Y/month_%m/day_%d/'
                        'master_scoreboard.json')
    resp = sess.get(url)
    log_cookies()
    games = json.loads(resp.text)['data']['games']['game']

    cookie_jar.save()
    return games


def get_game_video(event_id):
    login()
    cookies = {c.name: c.value for c in cookie_jar}
    session = urllib.unquote(cookies['ftmu']) if 'ftmu' in cookies else None

    data = {
        'eventId': event_id,
        'sessionKey': session,
        'fingerprint': urllib.unquote(cookies['fprt']),
        'identityPointId': cookies['ipid'],
        'subject': 'LIVE_EVENT_COVERAGE',
        'platform': 'WEB_MEDIAPLAYER'
    }
    url = 'https://mlb-ws.mlb.com/pubajaxws/bamrest/MediaService2_0/op-findUserVerifiedEvent/v-2.3?'
    headers = {
        'User-agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:19.0) Gecko/20100101 Firefox/19.0',
        'Referer': 'http://mlb.mlb.com/shared/flash/mediaplayer/v4.4/R8/MediaPlayer4.swf?'
    }
    resp = sess.post(url, data, headers=headers)
    soup = BeautifulStoneSoup(resp.text)
    status = soup.find('status-code').string

    if status != '1':
        raise Exception(SOAP_CODES.get(status, 'Unknown error'))

    log_cookies("After findUserVerifiedEvent")
    session_key = soup.find('session-key')
    session = session_key.string if session_key else None
    event_id = soup.find('event-id').string
    items = soup.findAll('user-verified-content')
    verified_content = {'video': defaultdict(list), 'audio': defaultdict(list)}

    def attr(item, name):
        l = item('domain-attribute', attrs={'name': name})
        return l[0].string if l else ''

    for item in items:
        state = item.state.string
        if state == 'MEDIA_ARCHIVE':
            if int(event_id.split('-')[2]) < 2012:
                raise NotImplementedError("Pre-2012 archived content")
            else:
                scenario = 'FMS_CLOUD'
            live = False
        elif state == 'MEDIA_OFF':
            continue
        else:
            scenario = 'FMS_CLOUD'
            live = True
        content_id = item('content-id')[0].string

        # TODO: handle blackout

        call_letters = attr(item, 'call_letters')
        home_team_id = attr(item, 'home_team_id')
        away_team_id = attr(item, 'away_team_id')
        coverage_team_id = attr(item, 'coverage_association')

        if home_team_id == coverage_team_id:
            coverage = TEAM_CODES[home_team_id][0] + ' Coverage'
        elif away_team_id == coverage_team_id:
            coverage = TEAM_CODES[away_team_id][0] + ' Coverage'
        else:
            coverage = ''

        name = '{} - {}'.format(coverage, call_letters).replace('.', '').strip()

        if item.type.string == 'audio':
            name += ' Gameday Audio'
            scenario = 'AUDIO_FMS_32K'
            verified_content['audio'][coverage_team_id].append((name, event_id, content_id,
                                                                session, scenario, live))
        else:
            verified_content['video'][coverage_team_id].append((name, event_id, content_id,
                                                                session, scenario, live))

    return verified_content


def get_game_url(name, event, content, session, scenario, live):
    url = 'https://secure.mlb.com/pubajaxws/bamrest/MediaService2_0/op-findUserVerifiedEvent/v-2.3?'
    cookies = {c.name: c.value for c in cookie_jar}
    data = {
        'subject': 'LIVE_EVENT_COVERAGE',
        'sessionKey': session,
        'identityPointId': cookies['ipid'],
        'contentId': content,
        'playbackScenario': scenario,
        'eventId': event,
        'fingerprint': cookies['fprt'],
        'platform': 'WEB_MEDIAPLAYER'
    }
    resp = sess.post(url, data)
    soup = BeautifulStoneSoup(resp.text, convertEntities=BeautifulStoneSoup.XML_ENTITIES)
    try:
        new_fprt = soup.find('updated-fingerprint').string
        if new_fprt:
            new_cookie = cookielib.Cookie(
                version=0, name='fprt', value=new_fprt, port=None, port_specified=False,
                domain='.mlb.com', domain_specified=False, domain_initial_dot=False,
                path='/', path_specified=True, secure=False, expires=None, discard=True,
                comment=None, comment_url=None, rest={'HttpOnly': None}, rfc2109=False)
            cookie_jar.set_cookie(new_cookie)
            cookie_jar.save(ignore_discard=True, ignore_expires=True)
            cookies['fprt'] = new_fprt
    except AttributeError:
        log.info('No New Fingerprint')

    status = soup.find('status-code').string
    if status != "1":
        raise Exception(SOAP_CODES.get(status, 'Unknown error'))

    if soup.find('state').string == 'MEDIA_OFF':
        raise Exception('Status : Media Off')  # Could check for preview

    # TODO: Deal with blackouts

    if 'notauthorizedstatus' in str(soup.find('auth-status')):
        raise Exception('Status : Not Authorized')  # Could check for preview

    try:
        game_url = (soup.findAll('user-verified-content')[0]
                    ('user-verified-media-item')[0]('url')[0].string)
    except:
        raise Exception('game_url not found')

    log.info("game_url: {}".format(game_url))

    if game_url.startswith('rtmp'):
        if 'live/' in game_url:
            rtmp = game_url.split('mlb_')[0]
            playpath = 'Playpath=mlb_'+game_url.split('mlb_')[1]
        elif 'ondemand' in game_url:
            rtmp = (game_url.split('ondemand/')[0] +
                    'ondemand?_fcs_vhost=cp65670.edgefcs.net&akmfv=1.6&' +
                    game_url.split('?')[1])
            playpath = 'Playpath='+game_url.split('ondemand/')[1]
    else:
        smil = get_smil(game_url.split('?')[0])
        rtmp = smil[0]
        playpath = 'Playpath='+smil[1]+'?'+game_url.split('?')[1]
        if 'ondemand' in rtmp:
            rtmp += ' app=ondemand?_fcs_vhost=cp65670.edgefcs.net&akmfv=1.6'+game_url.split('?')[1]

    log.info('Playpath: {}'.format(playpath))

    if 'mp3:' in game_url:
        pageurl = ('pageUrl=http://mlb.mlb.com/shared/flash/mediaplayer/v4.4/R8/MP4.jsp?calendar_'
                   'event_id={}&content_id={}&media_id=&view_key=&media_type=audio&source=MLB&spo'
                   'nsor=MLB&clickOrigin=Media+Grid&affiliateId=Media+Grid&feed_code='
                   'h&team=mlb'.format(soup.find('event-id').string, content))
    else:
        pageurl = ('pageUrl=http://mlb.mlb.com/shared/flash/mediaplayer/v4.4/R8/MP4.jsp?calendar_'
                   'event_id={}&content_id=&media_id=&view_key=&media_type=video&source=MLB&spons'
                   'or=MLB&clickOrigin=&affiliateId=&team=mlb'.format(soup.find('event-id').string))
    swfurl = 'swfUrl=http://mlb.mlb.com/shared/flash/mediaplayer/v4.4/R8/MediaPlayer4.swf swfVfy=1'
    if live:
        swfurl += ' live=1'
    final_url = ' '.join([rtmp, playpath, pageurl, swfurl])

    log.info('Name: {}'.format(name))
    log.info('Final url: {}'.format(final_url))
    return final_url


def login():
    cookies = {c.name: c.value for c in cookie_jar}
    if 'ipid' in cookies and 'fprt' in cookies:
        log.info("Already logged in, getting session cookie")
        log_cookies("Before:")
        sess.get('http://mlb.mlb.com/enterworkflow.do?flowId=media.media')
        log_cookies("After:")
    else:
        log.info("Beginning login")
        sess.get('https://secure.mlb.com/enterworkflow.do?flowId=registration.wizard&c_id=mlb')
        log_cookies()

        data = {
            'uri': '/account/login_register.jsp',
            'registrationAction': 'identify',
            'emailAddress': settings['email'],
            'password': settings['password'],
        }
        sess.post('https://secure.mlb.com/authenticate.do', data)
        log_cookies()
    cookie_jar.save()


def get_smil(url):
    resp = sess.get(url)
    soup = BeautifulStoneSoup(resp.text)
    # user_bitrate = '2400K'.replace('K', '000')  # TODO: Make this a setting
    log.info(soup('video'))
    best_el = max(soup('video'), key=lambda el: int(el['system-bitrate']))
    return soup.meta['base'], best_el['src']


if __name__ == '__main__':
    # REPL test code
    log.basicConfig(level=log.INFO)
    games = get_games()
    event_id = games[0]['game_media']['media'][0]['calendar_event_id']
    content = get_game_video(event_id)
    print(content)
    url = get_game_url(*content['video'][1])
