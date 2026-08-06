from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from natsort import natsorted


class MagicRename:
    magic_regex: dict[str, dict[str, str]] = {
        "$TV_REGEX": {
            "pattern": r".*?([Ss]\d{1,2})?(?:[第EePpXx\.\-\_\( ]{1,2}|^)(\d{1,3})(?!\d).*?\.(mp4|mkv)",
            "replace": r"\1E\2.\3",
        },
        "$BLACK_WORD": {
            "pattern": r"^(?!.*纯享)(?!.*加更)(?!.*超前企划)(?!.*训练室)(?!.*蒸蒸日上).*",
            "replace": "",
        },
        "$TV_MAGIC": {
            "pattern": r".*\.(mp4|mkv|mov|m4v|avi|mpeg|ts)$",
            "replace": r"{TASKNAME}.{SXX}E{E}.{EXT}",
        },
        "$SHOW_MAGIC": {
            "pattern": r"^(?!.*纯享)(?!.*加更)(?!.*抢先)(?!.*预告).*?第\d+期.*",
            "replace": r"{TASKNAME}.{SXX}E{II}.第{E}期{PART}.{EXT}",
        },
        "$SHOW_PRO": {
            "pattern": r"^(?!.*纯享)(?!.*加更)(?!.*抢先)(?!.*预告).*?第\d+期.*",
            "replace": r"{II}.{TASKNAME}.{DATE}.第{E}期{PART}.{EXT}",
        },
    }

    magic_variable: dict[str, Any] = {
        "{TASKNAME}": "",
        "{EXT}": [r"(?<=\.)\w+$"],
        "{CHINESE}": [r"[\u4e00-\u9fa5]{2,}"],
        "{DATE}": [
            r"(18|19|20)?\d{2}[\.\-/年]\d{1,2}[\.\-/月]\d{1,2}",
            r"(?<!\d)[12]\d{3}[01]?\d[0123]?\d",
            r"(?<!\d)[01]?\d[\.\-/月][0123]?\d",
        ],
        "{YEAR}": [r"(?<!\d)(18|19|20)\d{2}(?!\d)"],
        "{S}": [r"(?<=[Ss])\d{1,2}(?=[EeXx])", r"(?<=[Ss])\d{1,2}"],
        "{SXX}": [r"[Ss]\d{1,2}(?=[EeXx])", r"[Ss]\d{1,2}"],
        "{E}": [
            r"(?<=[Ss]\d\d[Ee])\d{1,3}",
            r"(?<=[Ee])\d{1,3}",
            r"(?<=[Ee][Pp])\d{1,3}",
            r"(?<=第)\d{1,3}(?=[集期话部篇])",
            r"(?<!\d)\d{1,3}(?=[集期话部篇])",
            r"(?!.*19)(?!.*20)(?<=[\._])\d{1,3}(?=[\._])",
            r"^\d{1,3}(?=\.\w+)",
            r"(?<!\d)\d{1,3}(?!\d)(?!$)",
        ],
        "{PART}": [r"(?<=[集期话部篇第])[上中下一二三四五六七八九十]", r"[上中下一二三四五六七八九十]"],
        "{VER}": [r"[\u4e00-\u9fa5]+版"],
        "{I}": "",
    }

    priority_list = [
        "更新",
        "超前点映",
        "抢先看",
        "加更",
        "精编版",
        "纯享",
        "未播",
        "彩蛋",
        "花絮",
        "番外",
        "幕后",
        "特辑",
        "预告",
        "合集",
        "特别篇",
        "先导片",
        "大结局",
        "结局",
        "完结",
        "上",
        "中",
        "下",
        "一",
        "二",
        "三",
        "四",
        "五",
        "六",
        "七",
        "八",
        "九",
        "十",
        "百",
        "千",
        "万",
    ]

    def __init__(self, magic_regex: dict[str, dict[str, str]] | None = None, magic_variable: dict[str, Any] | None = None):
        if magic_regex:
            self.magic_regex = dict(self.magic_regex)
            self.magic_regex.update(magic_regex)
        if magic_variable:
            self.magic_variable = dict(self.magic_variable)
            self.magic_variable.update(magic_variable)
        self.dir_filename_dict: dict[int, str] = {}
        self._compiled_cache: dict[str, re.Pattern[str]] = {}
        self._last_prep_key: tuple[str | None, str] | None = None
        self._last_compiled_pattern: re.Pattern[str] | None = None
        self._last_prep: list[tuple[str, str, list[re.Pattern[str]] | None]] | None = None

    def set_taskname(self, taskname: str) -> None:
        self.magic_variable["{TASKNAME}"] = taskname

    def magic_regex_conv(self, pattern: str, replace: str) -> tuple[str, str]:
        if pattern in self.magic_regex:
            actual = self.magic_regex[pattern]["pattern"]
            if replace == "":
                replace = self.magic_regex[pattern]["replace"]
            return actual, replace
        return pattern, replace

    def _get_compiled(self, pattern: str) -> re.Pattern[str]:
        cached = self._compiled_cache.get(pattern)
        if cached is not None:
            return cached
        compiled = re.compile(pattern)
        self._compiled_cache[pattern] = compiled
        return compiled

    def _prepare_sub(self, replace: str) -> list[tuple[str, str, list[re.Pattern[str]] | None]]:
        relevant: list[tuple[str, str, list[re.Pattern[str]] | None]] = []
        for key, p_list in self.magic_variable.items():
            if key not in replace:
                continue
            if key == "{I}":
                continue
            if key == "{TASKNAME}":
                relevant.append(("taskname", key, None))
                continue
            if p_list and isinstance(p_list, list):
                relevant.append(("regex", key, [self._get_compiled(p) for p in p_list]))
                continue
            relevant.append(("clear", key, None))
        return relevant

    def _sub_single(
        self,
        compiled_pattern: re.Pattern[str] | None,
        replace_template: str,
        prep: list[tuple[str, str, list[re.Pattern[str]] | None]],
        file_name: str,
    ) -> str:
        replace = replace_template
        for key_type, key, compiled_list in prep:
            if key_type == "taskname":
                replace = replace.replace(key, str(self.magic_variable.get("{TASKNAME}", "")))
                continue
            if key_type == "regex":
                matched = False
                for cp in compiled_list or []:
                    m = cp.search(file_name)
                    if not m:
                        continue
                    value = m.group()
                    if key == "{DATE}":
                        digits = "".join([c for c in value if c.isdigit()])
                        value = str(datetime.now().year)[: (8 - len(digits))] + digits
                    replace = replace.replace(key, value)
                    matched = True
                    break
                if not matched:
                    replace = replace.replace(key, "S01" if key == "{SXX}" else "")
                continue
            replace = replace.replace(key, "")

        if compiled_pattern is not None:
            return compiled_pattern.sub(replace, file_name)
        return replace

    def sub(self, pattern: str, replace: str, file_name: str) -> str:
        if not pattern and replace == "":
            return file_name
        cache_key = (pattern or None, replace)
        if cache_key != self._last_prep_key:
            self._last_compiled_pattern = self._get_compiled(pattern) if pattern else None
            self._last_prep = self._prepare_sub(replace)
            self._last_prep_key = cache_key
        return self._sub_single(self._last_compiled_pattern, replace, self._last_prep or [], file_name)

    def _custom_sort_key(self, name: str) -> str:
        value = name
        for i, keyword in enumerate(self.priority_list):
            if keyword in value:
                value = value.replace(keyword, f"_{i:02d}_")
        return value

    def set_dir_file_list(self, file_list: list[dict[str, Any]], replace: str, start_index: int = 1) -> None:
        self.dir_filename_dict = {}
        filename_list = [f["file_name"] for f in file_list if not f.get("dir")]
        filename_list.sort()
        if not filename_list:
            return

        compiled_i_pattern = self._get_compiled(r"\{I+\}")
        match = compiled_i_pattern.search(replace)
        if not match:
            return
        magic_i = match.group()
        pattern_i = r"\d" * magic_i.count("I")

        pattern = replace.replace(magic_i, "🔢")
        for key in list(self.magic_variable.keys()):
            if key in pattern:
                pattern = pattern.replace(key, "🔣")
        compiled_backref = self._get_compiled(r"\\[0-9]+")
        pattern = compiled_backref.sub("🔣", pattern)
        pattern = f"({re.escape(pattern).replace('🔣', '.*?').replace('🔢', f')({pattern_i})(')})"
        compiled_dir_pattern = re.compile(pattern)

        last_match = compiled_dir_pattern.match(filename_list[-1])
        if last_match:
            self.magic_variable["{I}"] = int(last_match.group(2))

        for filename in filename_list:
            m = compiled_dir_pattern.match(filename)
            if not m:
                continue
            self.dir_filename_dict[int(m.group(2))] = m.group(1) + magic_i + m.group(3)

        if not self.dir_filename_dict:
            self.magic_variable["{I}"] = start_index - 1

    def sort_file_list(self, file_list: list[dict[str, Any]], dir_filename_dict: dict[int, str] | None = None, start_index: int = 1) -> None:
        filename_list = [f"{f['file_name_re']}_{f['updated_at']}" for f in file_list if f.get("file_name_re") and not f.get("dir")]
        dir_filename_dict = dir_filename_dict or self.dir_filename_dict
        filename_list = list(set(filename_list) | set(dir_filename_dict.values()))
        filename_list = natsorted(filename_list, key=self._custom_sort_key)

        name_to_sorted_idx = {name: idx for idx, name in enumerate(filename_list)}
        dir_values_set = set(dir_filename_dict.values())

        filename_index: dict[str, int] = {}
        for name in filename_list:
            if name in dir_values_set:
                continue
            i = name_to_sorted_idx[name] + start_index
            while i in dir_filename_dict:
                i += 1
            dir_filename_dict[i] = name
            filename_index[name] = i

        compiled_i_pattern = self._get_compiled(r"\{I+\}")
        for file in file_list:
            if not file.get("file_name_re"):
                continue
            m = compiled_i_pattern.search(file["file_name_re"])
            if not m:
                continue
            key = f"{file['file_name_re']}_{file.get('updated_at')}"
            i = filename_index.get(key, 0)
            if not i:
                continue
            file["file_name_re"] = compiled_i_pattern.sub(str(i).zfill(m.group().count("I")), file["file_name_re"])

    def is_exists(self, filename: str, filename_list: list[str], ignore_ext: bool = False) -> str | None:
        if ignore_ext:
            filename = os.path.splitext(filename)[0]
            filename_list = [os.path.splitext(f)[0] for f in filename_list]

        compiled_i_pattern = self._get_compiled(r"\{I+\}")
        m = compiled_i_pattern.search(filename)
        if m:
            magic_i = m.group()
            pattern_i = r"\d" * magic_i.count("I")
            pattern = re.escape(filename).replace(re.escape(magic_i), pattern_i)
            compiled_exist = re.compile(pattern)
            for fn in filename_list:
                if compiled_exist.match(fn):
                    return fn
            return None
        return filename if filename in filename_list else None
