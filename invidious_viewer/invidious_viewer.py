import urllib.request
import feedparser
import argparse
import datetime
import json
import mpv
import os
import re

# Set ANSI escape codes for colors
CRED = "\033[91m"
CBLUE = "\33[34m"
CGREEN = "\33[32m"
CEND = "\033[0m"


def length(arg):
    try:
        return datetime.timedelta(seconds=arg)
    except TypeError:
        return arg


def download(url):
    content = urllib.request.urlopen(url).read()
    content = json.loads(content)
    return content


def player_config(player, video, captions):
    player.vid = "auto"
    player.terminal = False
    player.input_terminal = False
    if not captions:
        player.sid = False
    if not video:
        player.vid = False
        player.terminal = True
        player.input_terminal = True


def get_by_url(url, instance):
    # Replace instance with https://youtube.com/ for regex
    url = url.rsplit("/", 1)
    url = "https://youtube.com/{}".format(url[1])
    pattern = (r"(https?://)(youtube)\.(com)"
                "(/?playlist\?list=|watch\?v=|embed/|v/|.+\?v=)?([0-9A-Za-z-_]{10,})")
    content_id = re.findall(pattern, url)
    content_id = content_id[0][-1]
    # Video IDs have a length of 11 characters
    # Assume the ID to be of a playlist if length exceeds 11 characters
    if len(content_id) > 11:
        api_url = "{}/api/v1/playlists/{}".format(instance, content_id)
        content_type = "playlist"
    else:
        api_url = content_id
        content_type = "video"
    return content_type, api_url


def config(instance):
    config_path = os.path.expanduser("~/.config/invidious/")
    config_file = config_path + "config.json"
    config_dict = {"instance": instance, "play_video": True, "captions": False}
    if not os.path.exists(config_file):
        print("Created config file at {}".format(config_file))
        try:
            os.mkdir(config_path)
        except FileExistsError:
            pass
        with open(config_file, "w") as f:
            json.dump(config_dict, f, indent=4)
    with open(config_file, "r") as f:
        content = json.loads(f.read())
        return content


def get_data(content_type, results, instance, search_term=None, api_url=None):
    if "search" in content_type or "channel" in content_type:
        url = "{}/api/v1/search?q={}".format(instance, search_term)
    elif "popular" in content_type:
        url = "{}/api/v1/popular".format(instance)
    elif "trending" in content_type:
        url = "{}/api/v1/trending".format(instance)
    elif "playlist" in content_type:
        url = api_url
    elif "video" in content_type:
        return [api_url], 0
    rss = False
    video_ids = []
    title_list = []
    max_results = results
    content = download(url)
    if content_type == "playlist":
        content = content["videos"]
    elif content_type == "channel":
        content_ = content
        channel_url = "{}/api/v1/channels/videos/{}".format(instance,
                                                     content_[0]["authorId"])
        content = download(channel_url)
        # Fetch videos from RSS fead if invidious fails
        if len(content) == 0:
            rss = True
            # Make an empty dict to store data from RSS feed
            content = {}
            id_key = "videoId"
            title_key = "title"
            author_key = "author"
            length_key = "lengthSeconds"
            content.setdefault(id_key, [])
            content.setdefault(title_key, [])
            content.setdefault(author_key, [])
            content.setdefault(length_key, [])
            rss_feed = feedparser.parse("{}/feed/channel/{}".format(instance,
                                        content_[0]["authorId"]))
            rss_count = -1
            # RSS returns only 15 results
            while rss_count < 14:
                rss_count += 1
                entries = rss_feed.entries[rss_count]
                content[id_key].append(entries.yt_videoid)
                content[title_key].append(entries.title)
                content[author_key].append(entries.author)
                content[length_key].append(0)
    # Set maximum length for video titles
    max_len = 60
    # Get titles from dictionary or JSON data
    if rss:
        for title in content["title"]:
            title = title[:max_len]
            title_list.append(title)
    else:
        for title in content:
            title = title["title"][:max_len]
            title_list.append(title)
    # Get longest title out of the title list, used in content_loop() for properly padding
    # video length and channel name
    longest_title = len(max(title_list, key=len))
    count = 0
    def content_loop(loop_variable, count=count):
        for i in loop_variable:
            # Add 1 to the count to be displayed before each title
            count += 1
            if count <= 9:
                count_ = " {}".format(count)
            else:
                count_ = count
            # Stops the for loop if the maximum number of results have been printed out (Set by the --results argument)
            if max_results is not None and count > max_results:
                continue
            if rss:
                title = i[:max_len].ljust(longest_title)
                for item in content["author"]:
                    channel = item
                for item in content["videoId"]:
                    if item not in video_ids:
                        video_ids.append(item)
                for item in content["lengthSeconds"]:
                    video_length = length(item)
            else:
                title = i["title"][:max_len].ljust(longest_title)
                channel = i["author"]
                video_ids.append(i["videoId"])
                video_length = length(i["lengthSeconds"])
            results = "{}: {}{} {}\t[{}] {}{} {}".format(count_, CGREEN, title,
                                                        CBLUE, video_length, CRED,
                                                        channel, CEND)
            print(results)
    if rss:
        content_loop(content["title"])
    else:
        content_loop(content)
    queue_list = []
    if content_type == "search" or "playlist" or "popular":
        # Append user choice to queue
        for tries in range(4):
            try:
                queue = input("> ").split()
                # Add all results to queue if input has the string "all" in it
                if "all" in queue:
                    return video_ids, len(video_ids)
                for item in queue:
                    item = int(item) - 1
                    queue_list.append(item)
                break
            except ValueError:
                pass
        video_ids = [video_ids[i] for i in queue_list]
    return video_ids, len(queue_list)


def video_playback(video_ids, queue_length, instance, player):
    if queue_length == 0:
        queue_length = 1
    queue = 0
    for video_id in video_ids:
        queue += 1
        url = "{}/api/v1/videos/{}".format(instance, video_id)
        stream_url = download(url)
        title = stream_url["title"]
        print("[{} of {}] {}".format(queue, queue_length, title))
        try:
            # Get URL for 1080p video
            url = stream_url["adaptiveFormats"][-3]["url"]
            cc_url = stream_url["captions"][0]["url"]
            cc_url = "{}{}".format(instance, cc_url)
            # Set separate URL for audio file as 1080p URL ("adaptiveFormats") only has video content
            audio_url = stream_url["adaptiveFormats"][3]["url"]
            player.audio_files, player.sub_files = [audio_url], [cc_url]
        except IndexError:
            # Don't use old files
            player.audio_files, player.sub_files = [], []
            try:
                # Get URL for 720p video
                url = stream_url["formatStreams"][1]["url"]
            except IndexError:
                try:
                    # Get URL for 360p video
                    url = stream_url["formatStreams"][0]["url"]
                except IndexError:
                    try:
                    # Get URL for livestream
                        url = stream_url["hlsUrl"]
                    except KeyError:
                        print("No URL found")
        player.play(url)
        player.wait_for_playback()
    player.terminate()


def main():
    invidious_ascii = r'''
      _____            _     _ _
     |_   _|          (_)   | (_)
       | |  _ ____   ___  __| |_  ___  _   _ ___
       | | | '_ \ \ / / |/ _` | |/ _ \| | | / __|
      _| |_| | | \ V /| | (_| | | (_) | |_| \__ \
     |_____|_| |_|\_/ |_|\__,_|_|\___/ \__,_|___/
    '''
    print(invidious_ascii)
    parser = argparse.ArgumentParser()
    parser.add_argument(
                        "-i",
                        "--instance",
                        help="Specify a different invidious instance")
    parser.add_argument("-r",
                        "--results",
                        type=int,
                        help="Return specific number of results")
    parser.add_argument("-v",
                        "--video",
                        help="Toggle video playback",
                        action="store_true")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-u",
                       "--url",
                       help="Specify link or ID to play [Video/Playlist]")
    group.add_argument("-c",
                       "--channel",
                       help="View videos from a specific channel")
    group.add_argument("-p",
                       "--popular",
                       help="View popular videos (Default invidious page)",
                       action="store_true")
    group.add_argument("-t",
                       "--trending",
                       help="View trending videos",
                       action="store_true")
    args = parser.parse_args()
    player = mpv.MPV(ytdl=True,
                     input_default_bindings=True,
                     input_vo_keyboard=True,
                     osc=True)
    # Set "ENTER" as the keybind to skip to the next item in the queue
    player.on_key_press("ENTER")(lambda: player.playlist_next(mode="force"))
    default_instance = "https://invidious.snopyta.org"
    invidious_config = config(default_instance)
    url = args.url
    results = args.results
    video = invidious_config.get("play_video")
    instance = invidious_config.get("instance")
    captions = invidious_config.get("captions")
    video = not video if args.video else video
    instance = args.instance if args.instance is not None else instance
    if args.popular:
        video_ids = get_data("popular", results, instance)
    elif args.trending:
        video_ids = get_data("trending", results, instance)
    elif args.channel is not None:
        channel_name = "+".join(args.channel.split())
        video_ids = get_data("channel", results, instance, channel_name)
    elif args.url is not None:
        url = get_by_url(url, instance)
        video_ids = get_data(url[0], results, instance, api_url=url[1])
    else:
        search_term = "+".join(input("> ").split())
        video_ids = get_data("search", results, instance, search_term)
    player_config(player, video, captions)
    video_playback(video_ids[0], video_ids[1], instance, player)


if __name__ == "__main__":
    main()
