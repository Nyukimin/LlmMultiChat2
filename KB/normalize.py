from __future__ import annotations
import re
import unicodedata
from typing import Optional, Dict, Any

# Shared role vocabularies (extend as needed)
ROLE_KEYWORDS: Dict[str, str] = {
    "監督": "director",
    "主演": "actor",
    "出演": "actor",
    "キャスト": "actor",
    "声優": "voice",
    "脚本": "screenplay",
    "脚色": "screenplay",
    "原作": "author",
    "音楽": "composer",
}

ROLE_PREFIXES = [
    "出演", "主演", "監督", "脚本", "脚色", "原作", "音楽", "声優", "主題歌", "音響効果", "プロデューサー",
]

STATUS_PREFIXES = ["上映中", "配信中"]


def _nfkc_space(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "")
    s = s.replace("\u3000", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _remove_role_prefix(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return s
    for pref in ROLE_PREFIXES:
        if re.match(rf"^{re.escape(pref)}[：:・／/\s]", s):
            s = re.sub(rf"^{re.escape(pref)}[：:・／/\s]+", "", s, count=1).strip()
            break
        if s == pref:
            return ""
    return s


def _remove_status_prefix(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return s
    changed = True
    while changed:
        changed = False
        for pref in STATUS_PREFIXES:
            if re.match(rf"^{re.escape(pref)}[：:・／/\s]", s):
                s = re.sub(rf"^{re.escape(pref)}[：:・／/\s]+", "", s, count=1).strip()
                changed = True
    return s


def looks_like_role_list_plus_name(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    if ("/" in s or "／" in s) and re.search(r"(監督|脚本|脚色|製作|編集|出演|主演)", s):
        parts = re.split(r"\s+", s)
        if parts:
            last = parts[-1]
            if re.match(r"^[\u4E00-\u9FFF\u3040-\u30FFA-Za-z0-9]{2,}$", last):
                return True
    return False


def normalize_title(raw: str) -> tuple[str, Optional[int]]:
    s = _nfkc_space(raw)
    s = re.sub(r"[／/]+", " ", s)
    s = _remove_status_prefix(_remove_role_prefix(s))
    m = re.match(r"^(.*?)\s*[:：]\s*作品情報・キャスト・あらすじ\s*-\s*映画\.com(?:\s*\((\d{4})\))?\s*$", s)
    if m:
        name = _nfkc_space(m.group(1))
        year = int(m.group(2)) if m.group(2) else None
        return name, year
    m2 = re.match(r"^(.*)\((\d{4})\)\s*$", s)
    if m2 and not re.search(r"作品情報・キャスト・あらすじ", s):
        name = _nfkc_space(m2.group(1).rstrip("：:"))
        year = int(m2.group(2))
        return name, year
    return s, None


def normalize_person_name(raw: str) -> str:
    s = _nfkc_space(raw)
    s = re.sub(r"[／/]+", " ", s)
    s = _remove_status_prefix(_remove_role_prefix(s))
    if re.search(r"(作品情報|映画\.com|キャスト|あらすじ)", s):
        return ""
    if is_noise_person_name(s):
        return ""
    return s


def normalize_credit(credit: Dict[str, Any]) -> Dict[str, Any]:
    c = dict(credit)
    if c.get("work"):
        t, _y = normalize_title(str(c["work"]))
        c["work"] = t
    if c.get("person"):
        p = normalize_person_name(str(c["person"]))
        if not p:
            return {}
        c["person"] = p
    return c


def normalize_role(raw: str) -> str:
    s = _nfkc_space(raw)
    if s in ROLE_KEYWORDS:
        return ROLE_KEYWORDS[s]
    if re.match(r"^[a-z][a-z_]+$", s):
        return s
    return s


def normalize_character(raw: str) -> str:
    s = _nfkc_space(raw)
    s = re.sub(r"[／/]+", " ", s)
    if re.search(r"(作品情報|映画\.com|キャスト|あらすじ)", s):
        return ""
    return s


def is_noise_person_name(name: str) -> bool:
    s = (name or "").strip()
    if not s:
        return True
    patterns = [
        r"^©$|^\(C\)|^C\)$|^C\)$|^C\)$",
        r"映画\.com|レビュー|レビューガイドライン|レビューを書く|映画レビュー|映画ランキング|プライバシーポリシー|利用規約|サイトマップ|ヘルプ|公式アプリ|メール|メルマガ|アプリ|動画配信検索|企業情報|人材募集|お問い合わせ|プレゼント|採点する|並び替え|標準|評価の高い順|評価の低い順|全てのスタッフ|全て|全0件|関連ニュース|フォトギャラリー|トップへ戻る|この作品にレビューはまだ投稿されていません",
        r"Inc\.?$|LLC\.?$|Ltd\.?$|GmbH$|Partners?\.?$|Productions?$|Pictures?$|Studio?s?\.?$|Television$|International$|Company$|Co\.$",
        r"^and$|^All$|^BEST$|^ENTRY$|^MENU$|^Rights$|^rights$|^Reserved\.?$|^reserved\.?$|^SERVICES$|^SL$|^UPON$",
        r"^FILMS?$|^FILM$|^BASQUE$|^SYGNATIA$|^AIE$|^ALLTIME$|^Disney$|^Sony$|^Universal$|^Pixar\.?$|^Yukikaze$",
        r"^eiga\.com$|^orange-オレンジ-$|^集英社$|^国内ドラマ$|^海外ドラマ$|^映画$|^動画$|^ニュース$",
    ]
    for pat in patterns:
        if re.search(pat, s, re.IGNORECASE):
            return True
    if len(s) <= 1:
        return True
    if re.fullmatch(r"[\-–—•·・:;,.…]+", s):
        return True
    return False


