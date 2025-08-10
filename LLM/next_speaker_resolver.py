import re
import unicodedata
import difflib
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple

try:
    # パッケージとして読み込まれる場合（LLM.プレフィックス）
    from .log_manager import write_operation_log
except Exception:
    # スクリプト/モジュール単体で読み込まれる場合
    from log_manager import write_operation_log


@dataclass
class NextPolicy:
    allow_self_nomination: bool = False
    fallback: Literal["round_robin", "random"] = "round_robin"
    fuzzy_threshold: float = 0.85


def _normalize_name(raw: str) -> str:
    if raw is None:
        return ""
    # Unicode正規化（全角/半角、濁点などのゆらぎを吸収）
    s = unicodedata.normalize("NFKC", str(raw)).strip()
    # 外側の括弧/引用符を除去
    s = s.strip("\"'()（）[]「」『』<>")
    # 敬称を除去
    for suffix in ("さん", "様", "ちゃん", "君"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    # 前後空白を再度トリム
    s = s.strip()
    # 英字は大文字化
    s = "".join(ch.upper() if ch.isalpha() and ord(ch) < 128 else ch for ch in s)
    return s


def _extract_last_tag(text: str) -> Optional[str]:
    # <think> ... </think> を除去
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text or "", flags=re.IGNORECASE)
    # [Next: ...] の最後の出現を抽出
    matches = re.findall(r"\[(?:Next|next|NEXT)\s*:\s*([^\]]+)\]", cleaned)
    if not matches:
        return None
    return matches[-1].strip()


def _extract_json_next(text: str) -> Optional[str]:
    """応答中の JSON 片に {"next":"..."} が含まれていれば優先採用する"""
    if not text:
        return None
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    # まず簡易に "next":"..." を抜き出す
    m = re.findall(r'"next"\s*:\s*"([^"]+)"', cleaned)
    if m:
        return m[-1].strip()
    return None


def _build_synonyms(registry: List[Dict[str, str]]) -> Dict[str, str]:
    """正規化されたキー -> internal_id の辞書を生成"""
    mapping: Dict[str, str] = {}
    for m in registry:
        internal_id = m.get("internal_id") or m.get("name")
        display_name = m.get("display_name", "")
        short_name = m.get("short_name", "")

        if not internal_id:
            continue

        for v in {internal_id, display_name, short_name}:
            norm = _normalize_name(v)
            if norm:
                mapping[norm] = internal_id
    return mapping


def _round_robin_next(registry: List[Dict[str, str]], current_id: str) -> Optional[str]:
    ids = [m.get("internal_id") or m.get("name") for m in registry]
    ids = [i for i in ids if i]
    if not ids:
        return None
    if current_id not in ids:
        return ids[0]
    idx = ids.index(current_id)
    if len(ids) == 1:
        return None
    return ids[(idx + 1) % len(ids)]


def resolve_next_speaker(
    response_text: str,
    current_internal_id: str,
    registry: List[Dict[str, str]],
    policy: Optional[NextPolicy],
    operation_log_filename: str,
) -> Tuple[Optional[str], str, Optional[str], Optional[str]]:
    """
    次話者 internal_id, 決定理由, 抽出元文字列, 正規化後文字列 を返す。
    決定理由: "tag" | "fuzzy" | "round_robin" | "random" | "none"
    """
    policy = policy or NextPolicy()
    # JSONのnextがあれば最優先
    extracted = _extract_json_next(response_text)
    if not extracted:
        extracted = _extract_last_tag(response_text)
    normalized = _normalize_name(extracted) if extracted else None

    synonyms = _build_synonyms(registry)

    # 1) タグでの直接一致（internal/display/short)
    if normalized and normalized in synonyms:
        candidate = synonyms[normalized]
        if candidate == current_internal_id and not policy.allow_self_nomination:
            # 自己指名禁止→フォールバック
            pass
        else:
            write_operation_log(operation_log_filename, "INFO", "NextSpeakerResolver", f"Resolved by tag: raw={extracted}, normalized={normalized}, id={candidate}")
            return candidate, "tag", extracted, normalized

    # 2) 近似一致
    if normalized:
        choices = list(synonyms.keys())
        close = difflib.get_close_matches(normalized, choices, n=1, cutoff=policy.fuzzy_threshold)
        if close:
            candidate = synonyms[close[0]]
            if candidate != current_internal_id or policy.allow_self_nomination:
                write_operation_log(operation_log_filename, "INFO", "NextSpeakerResolver", f"Resolved by fuzzy: raw={extracted}, normalized={normalized}, id={candidate}")
                return candidate, "fuzzy", extracted, normalized

    # 3) フォールバック
    if policy.fallback == "round_robin":
        candidate = _round_robin_next(registry, current_internal_id)
        if candidate and (candidate != current_internal_id or policy.allow_self_nomination):
            write_operation_log(operation_log_filename, "INFO", "NextSpeakerResolver", f"Resolved by round_robin: current={current_internal_id}, next={candidate}")
            return candidate, "round_robin", extracted, normalized
    else:  # random
        import random
        ids = [m.get("internal_id") or m.get("name") for m in registry]
        ids = [i for i in ids if i and (i != current_internal_id or policy.allow_self_nomination)]
        if ids:
            candidate = random.choice(ids)
            write_operation_log(operation_log_filename, "INFO", "NextSpeakerResolver", f"Resolved by random: current={current_internal_id}, next={candidate}")
            return candidate, "random", extracted, normalized

    write_operation_log(operation_log_filename, "WARNING", "NextSpeakerResolver", f"No next speaker resolved: raw={extracted}, normalized={normalized}")
    return None, "none", extracted, normalized


