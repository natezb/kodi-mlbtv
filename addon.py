# -*- coding: utf-8 -*-
# Copyright 2016 Nate Bogdanowicz
import sys
import os
import os.path
import logging
import urlparse
import datetime
from collections import OrderedDict
from urllib import urlencode
from PIL import Image
import xbmc
import xbmcgui
import xbmcplugin
import mlb


# Directories
tmp_dir = xbmc.translatePath('special://temp/mlbtv')
img_dir = os.path.join(mlb.addon_dir, 'resources', 'images')

if not os.path.exists(tmp_dir):
    os.makedirs(tmp_dir)


color = {
    'Final': 'FFFFFFFF',
    'Game Over': 'FFAAAAAA',
    'In Progress': 'FF953C3C',
    'Pre-Game': 'AAAAAAFF',
    'Preview': 'AAAAAAFF',
    'Warmup': 'AAAAAAFF',
}


class KodiHandler(logging.Handler):
    LEVELS = {
        logging.CRITICAL: xbmc.LOGFATAL,
        logging.ERROR: xbmc.LOGERROR,
        logging.WARNING: xbmc.LOGWARNING,
        logging.INFO: xbmc.LOGINFO,
        logging.DEBUG: xbmc.LOGDEBUG,
    }

    def __init__(self):
        super(KodiHandler, self).__init__()

    def emit(self, record):
        msg = record.msg if isinstance(record.msg, basestring) else repr(record.msg)
        xbmc.log(msg, self.LEVELS[record.levelno])


if __name__ == '__main__':
    log = logging.getLogger()
    log.addHandler(KodiHandler())
    log.setLevel(logging.INFO)


class Addon(object):
    def __init__(self, argv, content_type):
        self.base_url = sys.argv[0]
        self.handle = int(sys.argv[1])
        self.args = self._unwrap_args(urlparse.parse_qs(sys.argv[2][1:]))
        xbmcplugin.setContent(self.handle, content_type)

    def _handle_url(self, url, args):
        url = url or self.base_url
        query_str = '?' + urlencode(args) if args else ''
        return url + query_str

    @staticmethod
    def _unwrap_args(args):
        return {k: (v[0] if len(v) == 1 else (v or None)) for k, v in args.items()}

    def add_list_item(self, label, args=None, url=None, properties={}, art={}, **kwds):
        url = self._handle_url(url, args)
        isFolder = kwds.pop('isFolder', not url)
        item = xbmcgui.ListItem(label, **kwds)
        item.setArt(art)
        item.select(True)
        for key, value in properties.items():
            item.setProperty(key, value)
        xbmcplugin.addDirectoryItem(handle=self.handle, url=url, listitem=item, isFolder=isFolder)
        return item

    def set_resolved_url(self, url, success=True):
        item = xbmcgui.ListItem(path=url)
        xbmcplugin.setResolvedUrl(self.handle, success, item)

    def end_directory(self):
        xbmcplugin.endOfDirectory(self.handle)


def join_images(path_1, path_2, out_path, margin=0, spacing=0, alpha=0.):
    img_1 = Image.open(path_1)
    img_2 = Image.open(path_2)

    width = img_1.size[0] + img_2.size[0] + 2 * margin + spacing
    height = max(img_1.size[1], img_2.size[1]) + 2 * margin

    s = int(0.5 * 255)
    new_img = Image.new('RGBA', (width, height), (s, s, s, int(alpha*255)))
    new_img.paste(img_1, (margin,
                          int((height - img_1.size[1])/2)), img_1)
    new_img.paste(img_2, (margin + spacing + img_1.size[0],
                          int((height - img_2.size[1])/2)), img_2)

    new_img.save(out_path)


def joined_img(home_code, away_code, name, src_dir, margin, spacing, alpha):
    img_path = os.path.join(tmp_dir, '{}_{}_{}.png'.format(home_code, away_code, name))
    if os.path.exists(img_path):
        return img_path

    home_path = os.path.join(src_dir, '{}.png'.format(home_code))
    away_path = os.path.join(src_dir, '{}.png'.format(away_code))
    join_images(home_path, away_path, img_path, margin, spacing, alpha)
    return img_path


def poster_img(home_code, away_code):
    return joined_img(home_code, away_code, 'poster', os.path.join(img_dir, 'logos', 'scaled'),
                      10, 20, 0.0)


def thumb_img(home_code, away_code):
    return joined_img(home_code, away_code, 'thumb', os.path.join(img_dir, 'logos', 'icons'),
                      2, 4, 0.0)


def fanart_path(team_code):
    path = os.path.join(img_dir, 'fanart', '{}.jpg'.format(team_code))
    if not os.path.exists(path):
        return os.path.join(img_dir, 'fanart', 'default.jpg')
    return path


def show_games(date):
    categories = ('In Progress', 'Warmup', 'Pre-Game', 'Game Over', 'Final')
    normal_groups = OrderedDict((category, []) for category in categories)
    fav_groups = OrderedDict((category, []) for category in categories)
    # label, args, isFolder

    for g in mlb.get_games(date):
        status = g['status']['status']  # 'In Progress', 'Final', 'Preview', 'Pre-Game', 'Game Over'
        log.info(status)
        status = 'Pre-Game' if status == 'Preview' else status

        if status not in categories:
            log.error("Unknown game status '{}'".format(status))
            continue

        fav_team_ids = mlb.settings['fav_team_ids']
        if g['home_team_id'] in fav_team_ids or g['away_team_id'] in fav_team_ids:
            fav_groups[status].append(g)
        else:
            normal_groups[status].append(g)

    items = []
    for groups in (fav_groups, normal_groups):
        for group in groups.values():
            def sort_key(game):
                hour_str, min_str = game['time'].split(':')
                is_pm = game['ampm'].lower() == 'pm'
                return (int(hour_str) + 12*int(is_pm), int(min_str), game['home_team_name'])

            for g in sorted(group, key=sort_key):
                media = g['game_media']['media']
                if isinstance(media, list):
                    media = media[0]
                event_id = media['calendar_event_id']
                time = g['time'] + ' ' + g['ampm']

                STATUS_LABEL = {
                    'Pre-Game': time,
                    'Preview': time,
                    'Warmup': 'Warmup',
                    'In Progress': 'Live',
                    'Game Over': 'Game Over',
                    'Final': 'Archived'
                }

                status = g['status']['status']
                status_str = STATUS_LABEL.get(status, 'Unknown')
                STR = "[COLOR={}]{}[/COLOR] - {} [COLOR=FFAAAAAA]vs[/COLOR] {}"
                label = STR.format(color.get(status, 'FFFFFFFF'), status_str, g['home_team_name'],
                                   g['away_team_name'])

                playable = 'true' if status in ('In Progress', 'Final') else 'false'
                art = {'fanart': fanart_path(g['home_file_code']),
                       'banner': poster_img(g['home_file_code'], g['away_file_code']),
                       'thumb': thumb_img(g['home_file_code'], g['away_file_code'])}
                item = addon.add_list_item(label, args={'mode': 'game', 'event_id': event_id},
                                           isFolder=False, properties={'IsPlayable': playable},
                                           art=art)
                items.append(item)

    return items


def parse_date(date_str):
    """Parse simple %Y-%m-%d string into a date. Needed b/c strptime fails with Kodi"""
    return datetime.date(*(int(n) for n in date_str.split('-')))


if __name__ == '__main__':
    addon = Addon(sys.argv, 'movies')
    mode = addon.args.get('mode', 'main_menu')
    fmt = '%Y-%m-%d'
    today_str = datetime.date.today().strftime(fmt)
    date_str = addon.args.get('date', today_str)
    date = parse_date(date_str)
    prev_day = date - datetime.timedelta(1)
    next_day = date + datetime.timedelta(1)

    if mode == 'main_menu':
        art = {'fanart': fanart_path('default'), 'thumb': 'scroll-left.png'}
        addon.add_list_item(prev_day.strftime("%A's Games"), iconImage='scroll-left.png',
                            args={'mode': 'main_menu', 'date': prev_day.strftime(fmt)},
                            isFolder=True)
        # if date < datetime.date.today():
        #     addon.add_list_item(next_day.strftime("%A's Games"), iconImage='scroll-right.png',
        #                         args={'mode': 'main_menu', 'date': next_day.strftime(fmt)},
        #                         isFolder=True)
        show_games(date)
        addon.end_directory()
    elif mode == 'game':
        content = mlb.get_game_video(addon.args['event_id'])
        log.info(content)

        fav_team_ids = mlb.settings['fav_team_ids']
        preferred_ids = [b_id for b_id in content['video'] if b_id in fav_team_ids]
        xbmc.log(str(content))
        if len(preferred_ids) == 1:
            content_tup = content['video'][preferred_ids[0]][0]
        else:
            names = []
            content_tups = []
            for kind in ('video', 'audio'):
                for tup in content['video'].values():
                    names.append(tup[0])
                    content_tups.append(tup)

            dialog = xbmcgui.Dialog()
            ret = dialog.select('Choose Broadcast', names)
            content_tup = content_tups[ret] if ret >= 0 else None

        url = mlb.get_game_url(*content_tup)
        addon.set_resolved_url(url)
