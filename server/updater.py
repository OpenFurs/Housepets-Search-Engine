import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import redis
import requests
from bs4 import BeautifulSoup
from colorama import *
from redis.commands.search.field import NumericField
from redis.commands.search.field import TagField
from redis.commands.search.field import TextField
from redis.commands.search.indexDefinition import IndexDefinition
from redis.commands.search.query import Query

rs = requests.Session()


def main():
    global rs
    with open("./redis_config.json") as f:
        redis_config = json.load(f)

    # setup and connect to redis and the database
    print("Connecting to redis...")
    if redis_config["database"]["password"] is None:
        RedisDB = redis.StrictRedis(
            host=redis_config["database"]["host"],
            port=int(redis_config["database"]["port"]),
            username=redis_config["database"]["username"],
        )
    else:
        RedisDB = redis.StrictRedis(
            host=redis_config["database"]["host"],
            port=int(redis_config["database"]["port"]),
            username=redis_config["database"]["username"],
            password=redis_config["database"]["password"],
        )

    # crate a schema for the comic's data
    schema = (
        TextField("title"),
        TextField("comic_link"),
        TagField("characters"),
        TextField("image"),
        NumericField("index", sortable=True),
    )

    init(wrap=False)
    stream = AnsiToWin32(sys.stderr).stream

    user_agent = {
        "user-agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_5)"
                       "AppleWebKit/537.36 (KHTML, like Gecko)"
                       "Chrome/45.0.2454.101 Safari/537.36"),
        "referer":
        "https://www.housepetscomic.com",
    }

    housepets_db = {}
    print(
        f"{Back.YELLOW}{Fore.LIGHTWHITE_EX}{Style.BRIGHT} Generating Housepets database... {Style.RESET_ALL}"
    )

    while True:
        time.sleep(5)
        # grabs today year
        year = time.strftime("%Y")
        # grab the redis list of characters
        characters = RedisDB.lrange("characters_db", 0, -1)
        # turn it to a list of strings
        characters = [character for character in characters]
        characters_db = set(characters)

        print("characters_db length:", len(characters_db))

        # grab todays year database hash index
        year_db = RedisDB.ft(year).search(Query("*").paging(0, 500))

        print("year_db length:", len(year_db))

        web = rs.get(
            f"https://www.housepetscomic.com/archive/?archive_year={year}")
        soup = BeautifulSoup(web.text, "html.parser")
        link_tag = soup.find_all("a", {
            "rel": "bookmark",
            "href": re.compile("^https://")
        })

        if len(link_tag) > len(year_db):
            print(len(link_tag))
            print(year_db)
            print(
                f"{Back.YELLOW}{Fore.LIGHTWHITE_EX}{Style.BRIGHT} New comics found! {Style.RESET_ALL}"
            )
            # create an index for the comics pecific year
            index_def = IndexDefinition(prefix=[f"{year}:"],
                                        score=0.5,
                                        score_field="doc_score")

            try:
                print(
                    f"{Back.YELLOW}{Fore.LIGHTWHITE_EX}{Style.BRIGHT} Setting up {year} index... {Style.RESET_ALL}"
                )
                RedisDB.ft(f"{year}").create_index(schema,
                                                   definition=index_def)
            except Exception as e:
                print(
                    f"{Back.RED}{Fore.LIGHTWHITE_EX}{Style.BRIGHT} {year} index already exists {Style.RESET_ALL}"
                )

            print(
                f"Searching in year {Fore.GREEN}{Style.BRIGHT}{year}{Style.RESET_ALL}"
            )

            web = rs.get(
                f"https://www.housepetscomic.com/archive/?archive_year={year}",
                headers=user_agent,
                timeout=None,
            )
            soup = BeautifulSoup(web.text, "html.parser")
            link_tag = soup.find_all("a", {
                "rel": "bookmark",
                "href": re.compile("^https://")
            })
            print(
                f"Found {Fore.GREEN}{Style.BRIGHT}{len(link_tag)}{Style.RESET_ALL} tags!"
            )

            for index, link in enumerate(link_tag, start=1):
                link = link.get("href")
                link_page = rs.get(link, headers=user_agent, timeout=None)
                if "https://www.housepetscomic.com/character" in link_page.text:
                    print(link)

                    characters = []
                    comic_soup = BeautifulSoup(link_page.text, "html.parser")
                    characters_tag = comic_soup.find_all(
                        "a",
                        {
                            "href":
                            re.compile(
                                "^https://www\.housepetscomic\.com/character")
                        },
                    )
                    for character in characters_tag:
                        characters.append(character.text.lower())
                        characters_db.add(character.text.lower())

                    comic_image = comic_soup.find("img", {
                        "title": True,
                        "alt": True
                    })

                    print(comic_image.get("src"))
                    link_title = link.split("/")[-2]

                    print(link_title)
                    RedisDB.hset(
                        f"{year}:{link_title}",
                        mapping={
                            # The character "u\u2013" is the unicode for the dash
                            "title":
                            comic_soup.title.text.split(" \u2013 ")[0],
                            "comic_link": link,
                            "characters": ",".join(characters),
                            "image": comic_image.get("src"),
                            "index": index,
                        },
                    )
                else:
                    print(
                        f"{Fore.BLACK}{Back.LIGHTWHITE_EX}{Style.BRIGHT}{link} is a guest comics{Style.RESET_ALL}"
                    )

            RedisDB.lset("characters_db", 0, *characters_db)


with ThreadPoolExecutor(max_workers=55) as executor:
    executor.map(main, range(155))

if __name__ == "__main__":
    main()
