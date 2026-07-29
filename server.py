from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


HOST = "127.0.0.1"
PORT = 8000
APP_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = APP_DIR / "public"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


QUESTION_FLOW = [
    {
        "key": "destination",
        "text": "我先确认目的地和天数。你准备去哪个城市，玩几天？",
        "quick_replies": ["上海，3 天", "杭州，2 天", "成都，4 天"],
        "required": True,
    },
    {
        "key": "travel_dates",
        "text": "出行日期是哪几天？这会影响营业时间、预约和价格判断。",
        "quick_replies": ["8 月 16 日到 8 月 18 日", "国庆假期", "日期还没完全确定"],
        "required": True,
    },
    {
        "key": "arrival_departure",
        "text": "第一天大概几点到？最后一天大概几点离开？",
        "quick_replies": ["10:30 到，17:30 走", "下午到，中午走", "还没买票"],
        "required": True,
    },
    {
        "key": "companions",
        "text": "同行人数和关系是怎样的？我会据此控制节奏和餐饮安排。",
        "quick_replies": ["2 人，朋友出行", "2 人，情侣出行", "1 人独自旅行"],
        "required": True,
    },
    {
        "key": "budget",
        "text": "预算范围大概是什么？不需要很精确，给一个档位就可以。",
        "quick_replies": ["经济一点", "适中预算", "品质优先"],
        "required": True,
    },
    {
        "key": "must_go",
        "text": "哪些地点是一定要去的？我会优先保留，除非出现重大冲突再请你确认。",
        "quick_replies": ["外滩、武康路、上海博物馆", "都想去，你帮我排", "我还没想好"],
        "required": True,
    },
    {
        "key": "pace",
        "text": "你更偏好的默认旅行节奏是什么？我会优先展示最匹配的方案，其他方案作为备选。",
        "quick_replies": ["适中，不要太累", "松弛一点", "高效打卡"],
        "required": True,
    },
    {
        "key": "transport",
        "text": "交通偏好呢？如果路线不顺，能接受每天打车 1-2 次吗？",
        "quick_replies": ["地铁为主，必要时打车", "尽量不打车", "打车优先"],
        "required": True,
    },
    {
        "key": "hotel_area",
        "text": "酒店区域确定了吗？如果没有，我会按市中心方便出行为默认。",
        "quick_replies": ["人民广场附近", "还没订，你帮我判断", "住景点附近"],
        "required": False,
    },
]


@dataclass
class ImportedSource:
    type: str
    content: str = ""
    filename: str = ""


@dataclass
class TravelSession:
    id: str
    initial_input: str
    source: ImportedSource
    answers: dict[str, str] = field(default_factory=dict)
    current_question_index: int = 0
    status: str = "collecting"
    recommended_plan_id: str = "smooth"
    confirmed_plan_id: str | None = None


SESSIONS: dict[str, TravelSession] = {}


POI_DB: dict[str, dict[str, Any]] = {
    "外滩": {
        "standard_name": "外滩",
        "address": "上海市黄浦区中山东一路",
        "type": "夜景/城市景观",
        "business_hours": "全天开放",
        "price": "免费",
        "visit_duration": "60-90 分钟",
        "best_time": "夜晚",
        "reservation_required": False,
        "confidence": "confirmed",
    },
    "北外滩": {
        "standard_name": "北外滩滨江绿地",
        "address": "上海市虹口区北外滩区域",
        "type": "夜景/滨江景观",
        "business_hours": "全天开放",
        "price": "免费",
        "visit_duration": "45-75 分钟",
        "best_time": "傍晚/夜晚",
        "reservation_required": False,
        "confidence": "confirmed",
    },
    "武康路": {
        "standard_name": "武康路历史文化名街",
        "address": "上海市徐汇区武康路",
        "type": "街区/拍照",
        "business_hours": "街区全天开放，店铺时间不一",
        "price": "免费",
        "visit_duration": "90-120 分钟",
        "best_time": "上午/下午",
        "reservation_required": False,
        "confidence": "confirmed",
    },
    "安福路": {
        "standard_name": "安福路",
        "address": "上海市徐汇区安福路",
        "type": "街区/咖啡/买手店",
        "business_hours": "街区全天开放，店铺时间不一",
        "price": "按消费",
        "visit_duration": "90-120 分钟",
        "best_time": "下午",
        "reservation_required": False,
        "confidence": "confirmed",
    },
    "豫园": {
        "standard_name": "豫园",
        "address": "上海市黄浦区福佑路168号",
        "type": "景点/园林",
        "business_hours": "通常白天开放，节假日可能调整",
        "price": "门票价格可能变化",
        "visit_duration": "90-120 分钟",
        "best_time": "下午/傍晚",
        "reservation_required": False,
        "confidence": "variable",
    },
    "上海博物馆": {
        "standard_name": "上海博物馆",
        "address": "上海市黄浦区人民大道201号",
        "type": "博物馆/文化",
        "business_hours": "通常白天开放，周一和特殊日期需确认",
        "price": "免费或特展收费，以官方为准",
        "visit_duration": "2-3 小时",
        "best_time": "上午/下午",
        "reservation_required": True,
        "confidence": "pending",
    },
    "静安寺": {
        "standard_name": "静安寺",
        "address": "上海市静安区南京西路1686号",
        "type": "景点/寺庙/商圈",
        "business_hours": "白天开放，具体时间需确认",
        "price": "门票可能变化",
        "visit_duration": "45-75 分钟",
        "best_time": "下午/傍晚",
        "reservation_required": False,
        "confidence": "pending",
    },
    "TX 淮海": {
        "standard_name": "TX 淮海",
        "address": "上海市黄浦区淮海中路523号",
        "type": "商场/潮流购物",
        "business_hours": "通常 10:00-22:00，具体以商场为准",
        "price": "按消费",
        "visit_duration": "60-120 分钟",
        "best_time": "下午/晚上",
        "reservation_required": False,
        "confidence": "confirmed",
    },
    "蟹黄面店": {
        "standard_name": "蟹黄面店",
        "address": "需确认具体门店",
        "type": "餐厅/本地美食",
        "business_hours": "不同门店差异较大",
        "price": "人均可能较高，需确认",
        "visit_duration": "60-90 分钟",
        "best_time": "午餐/晚餐",
        "reservation_required": False,
        "confidence": "pending",
    },
    "陆家嘴": {
        "standard_name": "陆家嘴",
        "address": "上海市浦东新区陆家嘴区域",
        "type": "城市景观/商圈",
        "business_hours": "区域全天开放，具体场馆时间不一",
        "price": "免费，观景台另计",
        "visit_duration": "90-120 分钟",
        "best_time": "下午/夜晚",
        "reservation_required": False,
        "confidence": "confirmed",
    },
}


def parse_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    content_length = int(handler.headers.get("Content-Length", "0"))
    if content_length == 0:
        return {}
    raw = handler.rfile.read(content_length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def extract_places(text: str) -> list[dict[str, Any]]:
    candidates = [
        "外滩",
        "北外滩",
        "武康路",
        "安福路",
        "豫园",
        "上海博物馆",
        "静安寺",
        "TX 淮海",
        "TX淮海",
        "蟹黄面店",
        "陆家嘴",
    ]
    places = []
    for name in candidates:
        if name in text:
            normalized = "TX 淮海" if name == "TX淮海" else name
            must_go_pattern = rf"{re.escape(name)}[ \t]*必去|必去[ \t]*{re.escape(name)}"
            places.append(
                {
                    "name": normalized,
                    "priority": "must_go" if re.search(must_go_pattern, text) else "interested",
                }
            )
    seen = set()
    unique_places = []
    for place in places:
        if place["name"] not in seen:
            seen.add(place["name"])
            unique_places.append(place)
    return unique_places


def import_payload(source_type: str, body: dict[str, Any]) -> dict[str, Any]:
    content = str(body.get("content", ""))
    url = str(body.get("url", ""))
    filename = str(body.get("filename", ""))
    extracted_text = str(body.get("extracted_text", ""))

    if source_type == "text":
        source_text = content
        source_label = "文本导入"
    elif source_type == "image":
        source_text = extracted_text or content
        source_label = filename or "截图导入"
    elif source_type == "link":
        source_text = content or url
        source_label = url or "链接导入"
    else:
        source_text = content
        source_label = "未知来源"

    places = extract_places(source_text)
    return {
        "source": {
            "type": source_type,
            "label": source_label,
            "url": url,
            "filename": filename,
        },
        "recognized_places": places,
        "unrecognized_text": source_text if not places else "",
        "needs_confirmation": len(places) == 0,
        "message": "已识别收藏地点。" if places else "暂未识别到明确地点，需要用户补充地点名称。",
    }


def enrich_place_name(name: str, priority: str = "interested") -> dict[str, Any]:
    normalized = "TX 淮海" if name == "TX淮海" else name
    poi = POI_DB.get(normalized)
    if not poi:
        return {
            "input_name": name,
            "standard_name": name,
            "address": "待补全",
            "type": "未知",
            "business_hours": "待确认",
            "price": "待确认",
            "visit_duration": "待确认",
            "best_time": "待确认",
            "reservation_required": None,
            "priority": priority,
            "confidence": confidence("pending"),
            "needs_confirmation": True,
        }

    return {
        "input_name": name,
        **poi,
        "priority": priority,
        "confidence": confidence(str(poi["confidence"])),
        "needs_confirmation": poi["confidence"] != "confirmed",
    }


def enrich_places(places: list[Any]) -> list[dict[str, Any]]:
    enriched = []
    for item in places:
        if isinstance(item, str):
            enriched.append(enrich_place_name(item))
            continue
        if isinstance(item, dict):
            enriched.append(
                enrich_place_name(
                    str(item.get("name", "")),
                    str(item.get("priority", "interested")),
                )
            )
    return [item for item in enriched if item["input_name"]]


def find_plan(plan_payload: dict[str, Any], plan_id: str) -> dict[str, Any]:
    for plan in plan_payload["plans"]:
        if plan["id"] == plan_id:
            return plan
    return plan_payload["plans"][0]


def load_imported_places(session: TravelSession) -> list[dict[str, Any]]:
    raw = session.answers.get("imported_places", "[]")
    try:
        places = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return places if isinstance(places, list) else []


def collect_llm_context(session: TravelSession) -> dict[str, Any]:
    imported_places = load_imported_places(session)
    must_go_answer = session.answers.get("must_go", "")
    text_for_places = "\n".join(
        [
            session.initial_input,
            session.source.content,
            must_go_answer,
        ]
    )
    extracted_from_answers = extract_places(text_for_places)
    place_map: dict[str, dict[str, Any]] = {}
    for place in imported_places + extracted_from_answers:
        name = str(place.get("name", ""))
        if name:
            place_map[name] = place

    return {
        "initial_input": session.initial_input,
        "source": asdict(session.source),
        "answers": session.answers,
        "recognized_places": list(place_map.values()),
        "enriched_places": enrich_places(list(place_map.values())),
        "planning_rules": [
            "用户标记为必去的地点必须保留；如果存在重大冲突，只能提示用户确认，不能擅自删除。",
            "相似景点只能建议取舍；如果用户坚持都去，需要规划进去并说明代价。",
            "路线必须考虑地点远近，避免同一天跨区来回绕路。",
            "必须考虑营业时间、价格、预约信息；不确定时使用待确认或可能变化。",
            "输出 1-3 套方案，默认推荐方案必须匹配用户节奏偏好。",
            "每个安排都要给出简短理由或注意事项。",
        ],
    }


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def normalize_llm_plan_payload(payload: dict[str, Any], session: TravelSession) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("LLM response is not a JSON object")
    plans = payload.get("plans")
    if not isinstance(plans, list) or not plans:
        raise ValueError("LLM response missing plans")

    raw_recommended_plan_id = str(payload.get("recommended_plan_id") or plans[0].get("id") or "smooth")
    normalized_plans = []
    for index, plan in enumerate(plans[:3], start=1):
        raw_plan_id = str(plan.get("id") or "")
        plan_name = str(plan.get("name", f"方案 {index}"))
        if "松弛" in raw_plan_id or "松弛" in plan_name:
            plan_id = "relaxed"
        elif "高效" in raw_plan_id or "打卡" in raw_plan_id or "高效" in plan_name or "打卡" in plan_name:
            plan_id = "packed"
        elif "顺" in raw_plan_id or "顺" in plan_name or "适中" in plan_name:
            plan_id = "smooth"
        else:
            plan_id = ["smooth", "relaxed", "packed"][min(index - 1, 2)]
        days = plan.get("days")
        if not isinstance(days, list) or not days:
            raise ValueError("LLM plan missing days")
        normalized_days = []
        for day in days:
            items = day.get("items")
            if not isinstance(items, list):
                items = []
            normalized_items = []
            for item in items:
                confidence_value = item.get("confidence", {"code": "pending", "label": "待确认"})
                if isinstance(confidence_value, str):
                    if confidence_value in ("已确认", "confirmed"):
                        confidence_value = confidence("confirmed")
                    elif confidence_value in ("可能变化", "variable"):
                        confidence_value = confidence("variable")
                    else:
                        confidence_value = confidence("pending")
                normalized_items.append(
                    {
                        "time": str(item.get("time", "")),
                        "name": str(item.get("name", item.get("place", ""))),
                        "note": str(item.get("note", item.get("reason", ""))),
                        "confidence": confidence_value,
                    }
                )
            normalized_days.append(
                {
                    "day": str(day.get("day", f"Day {len(normalized_days) + 1}")),
                    "title": str(day.get("title", "每日路线")),
                    "strength": str(day.get("strength", "适中")),
                    "items": normalized_items,
                }
            )
        normalized_plans.append(
                {
                    "id": plan_id,
                    "name": plan_name,
                "role": "recommended" if plan_id == recommended_plan_id else "alternative",
                "summary": str(plan.get("summary", "")),
                "strength": str(plan.get("strength", "适中")),
                "estimated_budget": str(plan.get("estimated_budget", "待估算")),
                "days": normalized_days,
            }
        )

    if "松弛" in raw_recommended_plan_id:
        recommended_plan_id = "relaxed"
    elif "高效" in raw_recommended_plan_id or "打卡" in raw_recommended_plan_id:
        recommended_plan_id = "packed"
    elif raw_recommended_plan_id in {"smooth", "relaxed", "packed"}:
        recommended_plan_id = raw_recommended_plan_id
    else:
        recommended_plan_id = normalized_plans[0]["id"]

    if recommended_plan_id not in {plan["id"] for plan in normalized_plans}:
        recommended_plan_id = normalized_plans[0]["id"]
    for plan in normalized_plans:
        plan["role"] = "recommended" if plan["id"] == recommended_plan_id else "alternative"

    diagnostics = payload.get("diagnostics")
    if not isinstance(diagnostics, list):
        diagnostics = []

    session.recommended_plan_id = recommended_plan_id
    session.status = "planned"
    return {
        "session_id": session.id,
        "recommended_plan_id": recommended_plan_id,
        "diagnostics": diagnostics,
        "plans": normalized_plans,
        "answers": session.answers,
        "llm_used": True,
        "model": OPENAI_MODEL,
    }


def generate_plan_with_llm(session: TravelSession) -> dict[str, Any]:
    if OpenAI is None:
        raise RuntimeError("openai package is not installed")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not configured")

    client = OpenAI()
    context = collect_llm_context(session)
    prompt = {
        "role": "developer",
        "content": (
            "你是一个智能旅行规划 Agent。请只输出 JSON，不要输出 Markdown。"
            "生成的路线必须真实可执行，必须尊重用户必去地点，并对不确定信息标注置信状态。"
            "JSON 顶层字段必须包含 recommended_plan_id、diagnostics、plans。"
            "plans 最多 3 个。方案 id 请优先使用 smooth、relaxed、packed。每个 plan 包含 id、name、summary、strength、estimated_budget、days。"
            "每个 day 包含 day、title、strength、items。每个 item 包含 time、name、note、confidence。"
            "confidence 必须是对象：{code: confirmed|pending|variable, label: 已确认|待确认|可能变化}。"
        ),
    }
    user_input = {
        "role": "user",
        "content": json.dumps(context, ensure_ascii=False),
    }
    response_obj = client.responses.create(
        model=OPENAI_MODEL,
        input=[prompt, user_input],
    )
    payload = extract_json_object(response_obj.output_text)
    return normalize_llm_plan_payload(payload, session)


def build_plans(session: TravelSession) -> dict[str, Any]:
    try:
        return generate_plan_with_llm(session)
    except Exception as exc:
        fallback = build_rule_based_plans(session)
        fallback["llm_used"] = False
        fallback["llm_error"] = str(exc)
        fallback["model"] = OPENAI_MODEL
        return fallback


def revise_plan(session: TravelSession, instruction: str, plan_id: str | None) -> dict[str, Any]:
    desired_plan_id = plan_id
    note = "已基于当前方案做局部调整。"

    if "太累" in instruction or "松弛" in instruction or "不要太累" in instruction:
        desired_plan_id = "relaxed"
        note = "已切换为松弛体验版：减少每日点位，保留必去地点，增加休息和返程缓冲。"
        session.answers["pace"] = "松弛一点"
    elif "高效" in instruction or "打卡" in instruction or "都想去" in instruction or "都要去" in instruction:
        desired_plan_id = "packed"
        note = "已切换为高效打卡版：尽量保留更多收藏地点，但会明确标注强度和重大冲突。"
        session.answers["pace"] = "高效打卡"
    elif "预算" in instruction or "便宜" in instruction or "省钱" in instruction:
        desired_plan_id = "relaxed"
        note = "已按降预算处理：减少打车和高消费停留，餐饮价格待确认项会继续保留提醒。"
        session.answers["budget"] = "经济一点"
    elif "不要早起" in instruction or "晚点" in instruction:
        desired_plan_id = "relaxed"
        note = "已调整为不早于 10:00 出门的松弛路线，高效方案将作为备选。"
        session.answers["pace"] = "松弛一点"

    revised_payload = build_plans(session)
    available_ids = {plan["id"] for plan in revised_payload["plans"]}
    active_plan_id = desired_plan_id if desired_plan_id in available_ids else revised_payload["recommended_plan_id"]
    revised_payload["recommended_plan_id"] = active_plan_id
    for plan in revised_payload["plans"]:
        plan["role"] = "recommended" if plan["id"] == active_plan_id else "alternative"

    session.recommended_plan_id = active_plan_id
    return {
        "session_id": session.id,
        "instruction": instruction,
        "revision_summary": note,
        "impact": {
            "time": "已重新平衡每日时间安排。",
            "budget": "如涉及预算，已优先减少高消费和打车安排。",
            "strength": "已根据用户指令调整路线强度。",
        },
        "recommended_plan_id": active_plan_id,
        "active_plan": find_plan(revised_payload, active_plan_id),
        "plans": revised_payload["plans"],
        "diagnostics": revised_payload["diagnostics"],
    }


def next_question(session: TravelSession) -> dict[str, Any] | None:
    if session.current_question_index >= len(QUESTION_FLOW):
        return None
    return QUESTION_FLOW[session.current_question_index]


def choose_recommended_plan(answers: dict[str, str]) -> str:
    pace = answers.get("pace", "")
    if "松弛" in pace:
        return "relaxed"
    if "高效" in pace or "打卡" in pace:
        return "packed"
    return "smooth"


def confidence(status: str) -> dict[str, str]:
    labels = {
        "confirmed": "已确认",
        "pending": "待确认",
        "variable": "可能变化",
    }
    return {"code": status, "label": labels[status]}


def make_place(time: str, name: str, note: str, status: str) -> dict[str, Any]:
    return {
        "time": time,
        "name": name,
        "note": note,
        "confidence": confidence(status),
    }


def build_rule_based_plans(session: TravelSession) -> dict[str, Any]:
    answers = session.answers
    recommended_plan_id = choose_recommended_plan(answers)
    session.recommended_plan_id = recommended_plan_id
    session.status = "planned"

    diagnostics = [
        {
            "type": "similarity",
            "severity": "medium",
            "title": "外滩与北外滩体验相似",
            "message": "两者都是浦江景观，AI 只建议取舍，不会擅自删除用户想去的地点。",
        },
        {
            "type": "booking",
            "severity": "medium",
            "title": "上海博物馆预约待确认",
            "message": "预约规则可能随日期变化，出发前需要二次确认。",
        },
        {
            "type": "price",
            "severity": "low",
            "title": "餐饮价格可能变化",
            "message": "蟹黄面店具体门店、人均消费和排队情况需要确认。",
        },
    ]

    plans = [
        {
            "id": "smooth",
            "name": "路线最顺版",
            "role": "recommended" if recommended_plan_id == "smooth" else "alternative",
            "summary": "按人民广场、衡复街区、浦江视角分组，减少跨区折返。",
            "strength": "适中",
            "estimated_budget": "约 980 元/人",
            "days": [
                {
                    "day": "Day 1",
                    "title": "人民广场与外滩夜景",
                    "strength": "适中",
                    "items": [
                        make_place("10:30", "抵达上海", "先到酒店寄存行李，首日不安排太赶。", "confirmed"),
                        make_place("12:00", "蟹黄面店", "午餐预留 1 小时；具体门店和价格需确认。", "pending"),
                        make_place("14:00", "上海博物馆", "用户必去；建议出发前确认预约规则。", "pending"),
                        make_place("17:30", "豫园", "与人民广场区域衔接较顺，傍晚体验更好。", "variable"),
                        make_place("20:00", "外滩", "用户必去；夜景时段更符合体验。", "confirmed"),
                    ],
                },
                {
                    "day": "Day 2",
                    "title": "衡复街区拍照与美食",
                    "strength": "轻松",
                    "items": [
                        make_place("10:00", "武康路", "用户必去；上午人流相对可控，适合拍照。", "confirmed"),
                        make_place("12:00", "安福路", "与武康路同区域，步行衔接，不绕路。", "confirmed"),
                        make_place("15:00", "TX 淮海", "作为休息和天气不好时的补充点。", "confirmed"),
                        make_place("18:00", "静安寺", "傍晚安排，减少全天步行压力。", "confirmed"),
                    ],
                },
                {
                    "day": "Day 3",
                    "title": "北外滩与返程缓冲",
                    "strength": "适中",
                    "items": [
                        make_place("10:00", "北外滩", "与外滩景观相似，但按用户收藏保留为补充视角。", "confirmed"),
                        make_place("12:30", "陆家嘴", "与北外滩隔江，适合补充城市天际线。", "confirmed"),
                        make_place("15:30", "返回酒店取行李", "预留离开前缓冲，避免赶车。", "confirmed"),
                    ],
                },
            ],
        },
        {
            "id": "relaxed",
            "name": "松弛体验版",
            "role": "recommended" if recommended_plan_id == "relaxed" else "alternative",
            "summary": "减少每日点位，保留必去地点，把同质景观作为备选处理。",
            "strength": "轻松",
            "estimated_budget": "约 860 元/人",
            "days": [
                {
                    "day": "Day 1",
                    "title": "博物馆与外滩",
                    "strength": "轻松",
                    "items": [
                        make_place("10:30", "抵达上海", "到酒店寄存，减少首日压力。", "confirmed"),
                        make_place("14:00", "上海博物馆", "必去地点，预留完整参观时间。", "pending"),
                        make_place("19:30", "外滩", "必去夜景点，不再叠加北外滩。", "confirmed"),
                    ],
                },
                {
                    "day": "Day 2",
                    "title": "武康路和安福路慢逛",
                    "strength": "轻松",
                    "items": [
                        make_place("10:30", "武康路", "不早起，留出拍照时间。", "confirmed"),
                        make_place("13:00", "安福路", "同区域吃饭、咖啡和逛店。", "confirmed"),
                        make_place("17:00", "静安寺", "傍晚轻量补充，不绕路。", "confirmed"),
                    ],
                },
                {
                    "day": "Day 3",
                    "title": "豫园与返程",
                    "strength": "轻松",
                    "items": [
                        make_place("10:00", "豫园", "半日经典点，适合返程日前半天。", "variable"),
                        make_place("13:30", "蟹黄面店", "价格和排队需确认。", "pending"),
                        make_place("15:30", "返回酒店取行李", "保留返程缓冲。", "confirmed"),
                    ],
                },
            ],
        },
        {
            "id": "packed",
            "name": "高效打卡版",
            "role": "recommended" if recommended_plan_id == "packed" else "alternative",
            "summary": "尽量纳入更多收藏地点，但强度更高，需要用户确认。",
            "strength": "偏累",
            "estimated_budget": "约 1180 元/人",
            "days": [
                {
                    "day": "Day 1",
                    "title": "人民广场、豫园、外滩",
                    "strength": "偏累",
                    "items": [
                        make_place("10:30", "抵达上海", "寄存后直接开始路线。", "confirmed"),
                        make_place("12:00", "蟹黄面店", "午餐后进入景点线。", "pending"),
                        make_place("13:30", "上海博物馆", "必去，但参观时间较紧。", "pending"),
                        make_place("16:30", "豫园", "需要控制停留时间。", "variable"),
                        make_place("19:30", "外滩", "必去夜景点。", "confirmed"),
                    ],
                },
                {
                    "day": "Day 2",
                    "title": "衡复、淮海、静安",
                    "strength": "偏累",
                    "items": [
                        make_place("09:30", "武康路", "早到更容易拍照，但略偏离不早起偏好。", "confirmed"),
                        make_place("11:30", "安福路", "同区域顺路。", "confirmed"),
                        make_place("14:30", "TX 淮海", "购物与休息。", "confirmed"),
                        make_place("17:30", "静安寺", "跨区补充，晚餐前后都可。", "confirmed"),
                    ],
                },
                {
                    "day": "Day 3",
                    "title": "双浦江视角",
                    "strength": "适中",
                    "items": [
                        make_place("10:00", "北外滩", "补充外滩之外的浦江视角。", "confirmed"),
                        make_place("12:30", "陆家嘴", "城市天际线打卡。", "confirmed"),
                        make_place("15:30", "返回酒店取行李", "返程缓冲较少，建议不要继续加点。", "confirmed"),
                    ],
                },
            ],
        },
    ]

    return {
        "session_id": session.id,
        "recommended_plan_id": recommended_plan_id,
        "diagnostics": diagnostics,
        "plans": plans,
        "answers": answers,
    }


def response(handler: BaseHTTPRequestHandler, status: int, body: dict[str, Any]) -> None:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(payload)


def not_found(handler: BaseHTTPRequestHandler) -> None:
    response(handler, 404, {"error": "not_found"})


def bad_request(handler: BaseHTTPRequestHandler, message: str) -> None:
    response(handler, 400, {"error": "bad_request", "message": message})


def get_session(session_id: str) -> TravelSession | None:
    return SESSIONS.get(session_id)


def serve_static(handler: BaseHTTPRequestHandler, path: str) -> bool:
    if path == "/":
        file_path = PUBLIC_DIR / "index.html"
    else:
        file_path = (PUBLIC_DIR / path.lstrip("/")).resolve()
        if PUBLIC_DIR.resolve() not in file_path.parents and file_path != PUBLIC_DIR.resolve():
            return False

    if not file_path.is_file():
        return False

    content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    data = file_path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)
    return True


class TravelAgentHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        response(self, 204, {})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            response(self, 200, {"status": "ok", "service": "travel-agent-backend"})
            return

        match = re.fullmatch(r"/api/sessions/([a-zA-Z0-9-]+)", parsed.path)
        if match:
            session = get_session(match.group(1))
            if not session:
                not_found(self)
                return
            response(
                self,
                200,
                {
                    "session": asdict(session),
                    "next_question": next_question(session),
                    "is_complete": next_question(session) is None,
                },
            )
            return

        if serve_static(self, parsed.path):
            return

        not_found(self)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        import_match = re.fullmatch(r"/api/import/(text|image|link)", parsed.path)
        if import_match:
            body = parse_body(self)
            response(self, 200, import_payload(import_match.group(1), body))
            return

        if parsed.path == "/api/places/enrich":
            body = parse_body(self)
            places = body.get("places", [])
            if isinstance(places, str):
                places = extract_places(places)
            if not isinstance(places, list):
                bad_request(self, "places must be a list or string")
                return
            enriched = enrich_places(places)
            response(
                self,
                200,
                {
                    "places": enriched,
                    "needs_confirmation_count": sum(1 for item in enriched if item["needs_confirmation"]),
                },
            )
            return

        if parsed.path == "/api/sessions":
            body = parse_body(self)
            initial_input = str(body.get("initial_input", ""))
            source_body = body.get("source", {})
            source = ImportedSource(
                type=str(source_body.get("type", "text")),
                content=str(source_body.get("content", "")),
                filename=str(source_body.get("filename", "")),
            )
            session = TravelSession(
                id=str(uuid.uuid4()),
                initial_input=initial_input,
                source=source,
            )
            places = extract_places(f"{initial_input}\n{source.content}")
            if places:
                session.answers["imported_places"] = json.dumps(places, ensure_ascii=False)
            SESSIONS[session.id] = session
            response(
                self,
                201,
                {
                    "session_id": session.id,
                    "next_question": next_question(session),
                    "imported_places": places,
                },
            )
            return

        answer_match = re.fullmatch(r"/api/sessions/([a-zA-Z0-9-]+)/answers", parsed.path)
        if answer_match:
            session = get_session(answer_match.group(1))
            if not session:
                not_found(self)
                return
            question = next_question(session)
            if not question:
                response(self, 200, {"is_complete": True, "next_question": None})
                return
            body = parse_body(self)
            answer = str(body.get("answer", "")).strip()
            if question["required"] and not answer:
                bad_request(self, "answer is required")
                return
            session.answers[question["key"]] = answer
            session.current_question_index += 1
            next_item = next_question(session)
            if next_item is None:
                session.status = "ready_to_plan"
            response(
                self,
                200,
                {
                    "session_id": session.id,
                    "accepted": True,
                    "is_complete": next_item is None,
                    "next_question": next_item,
                    "answers": session.answers,
                },
            )
            return

        plans_match = re.fullmatch(r"/api/sessions/([a-zA-Z0-9-]+)/plans", parsed.path)
        if plans_match:
            session = get_session(plans_match.group(1))
            if not session:
                not_found(self)
                return
            response(self, 200, build_plans(session))
            return

        revise_match = re.fullmatch(r"/api/sessions/([a-zA-Z0-9-]+)/revise", parsed.path)
        if revise_match:
            session = get_session(revise_match.group(1))
            if not session:
                not_found(self)
                return
            body = parse_body(self)
            instruction = str(body.get("instruction", "")).strip()
            if not instruction:
                bad_request(self, "instruction is required")
                return
            plan_id = body.get("plan_id")
            response(self, 200, revise_plan(session, instruction, str(plan_id) if plan_id else None))
            return

        confirm_match = re.fullmatch(r"/api/sessions/([a-zA-Z0-9-]+)/confirm", parsed.path)
        if confirm_match:
            session = get_session(confirm_match.group(1))
            if not session:
                not_found(self)
                return
            body = parse_body(self)
            plan_id = str(body.get("plan_id", session.recommended_plan_id))
            session.confirmed_plan_id = plan_id
            session.status = "confirmed"
            response(
                self,
                200,
                {
                    "session_id": session.id,
                    "confirmed_plan_id": plan_id,
                    "status": session.status,
                },
            )
            return

        not_found(self)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), TravelAgentHandler)
    url = f"http://{HOST}:{PORT}"
    print(f"Travel Agent app running at {url}")
    print("Press Ctrl+C to stop.")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
