from __future__ import annotations

from typing import Any

import requests


class DoubanClient:
    def __init__(self):
        self.base_url = "https://m.douban.com/rexxar/api/v2"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
                "Referer": "https://m.douban.com/",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            }
        )

    def get_categories(self) -> dict[str, Any]:
        return {
            "movie_hot": {
                "label": "热门电影",
                "media_type": "movie",
                "subs": ["全部", "华语", "欧美", "韩国", "日本"],
            },
            "movie_latest": {
                "label": "最新电影",
                "media_type": "movie",
                "subs": ["全部", "华语", "欧美", "韩国", "日本"],
            },
            "movie_top": {
                "label": "豆瓣高分",
                "media_type": "movie",
                "subs": ["全部", "华语", "欧美", "韩国", "日本"],
            },
            "movie_underrated": {
                "label": "冷门佳片",
                "media_type": "movie",
                "subs": ["全部", "华语", "欧美", "韩国", "日本"],
            },
            "tv_drama": {
                "label": "最近热门剧集",
                "media_type": "tv",
                "subs": ["综合", "国产剧", "欧美剧", "日剧", "韩剧", "动画", "纪录片"],
            },
            "tv_variety": {
                "label": "最近热门综艺",
                "media_type": "tv",
                "subs": ["综合", "国内", "国外"],
            },
        }

    def get_list_data(self, main_category: str, sub_category: str, *, limit: int = 20, start: int = 0) -> dict[str, Any]:
        try:
            if main_category.startswith("movie_"):
                return self._get_movie_ranking(main_category, sub_category, start=start, limit=limit)
            if main_category.startswith("tv_"):
                return self._get_tv_ranking(main_category, sub_category, start=start, limit=limit)
            return {"success": False, "message": f"不支持的主分类: {main_category}", "data": {"items": []}}
        except Exception as e:
            return {"success": False, "message": f"获取榜单数据失败: {str(e)}", "data": {"items": []}}

    def _process_item(self, item: dict[str, Any]) -> dict[str, Any] | None:
        try:
            pic_data = item.get("pic", {}) or {}
            pic_url = pic_data.get("normal", "") or pic_data.get("large", "") or ""

            rating_data = item.get("rating", {}) or {}
            rating = None
            if rating_data.get("value"):
                rating = {"value": rating_data.get("value")}

            original_url = item.get("url", "") or item.get("uri", "") or ""
            processed_url = ""
            if original_url:
                if original_url.startswith("douban://douban.com/"):
                    if "/movie/" in original_url:
                        movie_id = original_url.split("/movie/")[-1]
                        processed_url = f"https://movie.douban.com/subject/{movie_id}/"
                    elif "/tv/" in original_url:
                        tv_id = original_url.split("/tv/")[-1]
                        processed_url = f"https://movie.douban.com/subject/{tv_id}/"
                    else:
                        processed_url = original_url
                else:
                    processed_url = original_url

            title = str(item.get("title", "") or "").strip()
            if not title:
                return None

            return {
                "id": str(item.get("id", "") or ""),
                "title": title,
                "year": str(item.get("year", "") or ""),
                "url": processed_url,
                "pic": {"normal": pic_url},
                "rating": rating,
                "card_subtitle": str(item.get("card_subtitle", "") or ""),
            }
        except Exception:
            return None

    def _get_movie_ranking(self, main_category: str, sub_category: str, *, start: int = 0, limit: int = 20) -> dict[str, Any]:
        category_mapping = {
            "movie_hot": {"category": "热门", "default_type": "全部"},
            "movie_latest": {"category": "最新", "default_type": "全部"},
            "movie_top": {"category": "豆瓣高分", "default_type": "全部"},
            "movie_underrated": {"category": "冷门佳片", "default_type": "全部"},
        }
        cat = category_mapping.get(main_category, category_mapping["movie_hot"])

        params: dict[str, Any] = {"start": start, "limit": limit}
        if cat["category"] != "热门":
            params["category"] = cat["category"]
        if sub_category and sub_category != "全部":
            params["type"] = sub_category

        url = f"{self.base_url}/subject/recent_hot/movie"
        try:
            res = self.session.get(url, params=params, timeout=30)
            res.raise_for_status()
            if not res.text.strip():
                raise ValueError("API返回空响应")
            data = res.json()
            items = data.get("items", []) or data.get("subjects", []) or []
            processed: list[dict[str, Any]] = []
            for item in items[:limit]:
                row = self._process_item(item)
                if row:
                    processed.append(row)
            if not processed:
                return {
                    "success": True,
                    "message": "获取成功（模拟数据）",
                    "data": {"items": self._get_mock_movie_items(limit), "total": limit, "is_mock_data": True, "mock_reason": "API返回空数据"},
                }
            return {"success": True, "message": "获取成功", "data": {"items": processed, "total": data.get("total", len(processed))}}
        except Exception:
            return {
                "success": True,
                "message": "获取成功（模拟数据）",
                "data": {"items": self._get_mock_movie_items(limit), "total": limit, "is_mock_data": True, "mock_reason": "API调用失败"},
            }

    def _get_tv_ranking(self, main_category: str, sub_category: str, *, start: int = 0, limit: int = 20) -> dict[str, Any]:
        category_mapping = {
            "tv_drama": {"category": "tv", "default_type": "tv"},
            "tv_variety": {"category": "show", "default_type": "show"},
        }
        cat = category_mapping.get(main_category, category_mapping["tv_drama"])

        params: dict[str, Any] = {"start": start, "limit": limit}
        if sub_category:
            params["type"] = self._map_tv_sub_type(main_category, sub_category)
        if cat["category"] != "tv":
            params["category"] = cat["category"]

        url = f"{self.base_url}/subject/recent_hot/tv"
        try:
            res = self.session.get(url, params=params, timeout=30)
            res.raise_for_status()
            if not res.text.strip():
                raise ValueError("TV API返回空响应")
            data = res.json()
            items = data.get("items", []) or data.get("subjects", []) or []
            processed: list[dict[str, Any]] = []
            for item in items[:limit]:
                row = self._process_item(item)
                if row:
                    processed.append(row)
            if not processed:
                return {
                    "success": True,
                    "message": "获取成功（模拟数据）",
                    "data": {"items": self._get_mock_tv_items(limit), "total": limit, "is_mock_data": True, "mock_reason": "API返回空数据"},
                }
            return {"success": True, "message": "获取成功", "data": {"items": processed, "total": data.get("total", len(processed))}}
        except Exception:
            return {
                "success": True,
                "message": "获取成功（模拟数据）",
                "data": {"items": self._get_mock_tv_items(limit), "total": limit, "is_mock_data": True, "mock_reason": "API调用失败"},
            }

    def _map_tv_sub_type(self, main_category: str, sub_category: str) -> str:
        if main_category == "tv_variety":
            mapping = {"综合": "show", "国内": "show_domestic", "国外": "show_foreign"}
            return mapping.get(sub_category, "show")
        mapping = {
            "综合": "tv",
            "国产剧": "tv_domestic",
            "欧美剧": "tv_american",
            "日剧": "tv_japanese",
            "韩剧": "tv_korean",
            "动画": "tv_animation",
            "纪录片": "tv_documentary",
        }
        return mapping.get(sub_category, "tv")

    def _get_mock_movie_items(self, limit: int) -> list[dict[str, Any]]:
        base = [
            {
                "id": "1292052",
                "title": "肖申克的救赎",
                "rating": {"value": 9.7},
                "year": "1994",
                "url": "https://movie.douban.com/subject/1292052/",
                "pic": {"normal": ""},
                "card_subtitle": "1994 / 美国 / 剧情 犯罪 / 弗兰克·德拉邦特 / 蒂姆·罗宾斯 摩根·弗里曼",
            },
            {
                "id": "1291546",
                "title": "霸王别姬",
                "rating": {"value": 9.6},
                "year": "1993",
                "url": "https://movie.douban.com/subject/1291546/",
                "pic": {"normal": ""},
                "card_subtitle": "1993 / 中国大陆 香港 / 剧情 爱情 同性 / 陈凯歌 / 张国荣 张丰毅",
            },
            {
                "id": "1295644",
                "title": "阿甘正传",
                "rating": {"value": 9.5},
                "year": "1994",
                "url": "https://movie.douban.com/subject/1295644/",
                "pic": {"normal": ""},
                "card_subtitle": "1994 / 美国 / 剧情 爱情 / 罗伯特·泽米吉斯 / 汤姆·汉克斯 罗宾·怀特",
            },
        ]
        return base[: max(1, min(limit, len(base)))]

    def _get_mock_tv_items(self, limit: int) -> list[dict[str, Any]]:
        base = [
            {
                "id": "26794435",
                "title": "请回答1988",
                "rating": {"value": 9.7},
                "year": "2015",
                "url": "https://movie.douban.com/subject/26794435/",
                "pic": {"normal": ""},
                "card_subtitle": "2015 / 韩国 / 剧情 喜剧 家庭 / 申源浩 / 李惠利 朴宝剑",
            },
            {
                "id": "1309163",
                "title": "大明王朝1566",
                "rating": {"value": 9.7},
                "year": "2007",
                "url": "https://movie.douban.com/subject/1309163/",
                "pic": {"normal": ""},
                "card_subtitle": "2007 / 中国大陆 / 剧情 历史 / 张黎 / 陈宝国 黄志忠",
            },
            {
                "id": "1309169",
                "title": "亮剑",
                "rating": {"value": 9.3},
                "year": "2005",
                "url": "https://movie.douban.com/subject/1309169/",
                "pic": {"normal": ""},
                "card_subtitle": "2005 / 中国大陆 / 剧情 战争 / 陈健 张前 / 李幼斌 何政军",
            },
        ]
        return base[: max(1, min(limit, len(base)))]

