"""事实抽取与冲突判定。"""
import json
import re
from core import llm

EXTRACT_PROMPT = """你是记忆抽取器。从下面这段对话中，抽取"值得长期记住"的信息。

只抽五类：
- identity 身份：职业、学历、身份、当前所处状态
- preference 偏好：稳定地喜欢/讨厌/倾向什么
- goal 目标：想达成的事
- relation 关系：与他人的关系、称呼
- event 事件：发生了什么，尽量带时间

不要抽：闲聊寒暄、临时情绪、重复已有信息、对方只是提问的内容。

严格输出 JSON 数组，不要任何解释、不要代码块标记。每项格式：
{"subject":"用户","attribute":"简短属性名","value":"完整陈述","category":"identity|preference|goal|relation|event","confidence":0.9}

规则：
- subject 默认"用户"；明显指别人时写具体主体（如"字节跳动"）
- **attribute 必须是"对象+方面"的复合词，不允许用泛词**。反例（严禁）：投递状态、面试结果、技术成果、偏好、态度、状态。正例：字节_投递状态、搜狐_面试结果、对信息形式的态度、对解释长度的态度、家庭所在地、目标方向
- value 写成一句完整、脱离上下文也能看懂的话，不要代词
- event 类**必须写清对象+结果+关键数字**（例如"搜狐二面因项目深度不够被挂"，不要只写"聊了搜狐"）
- **一句话里出现多个对象时拆成多条**（"投了字节大模型和腾讯后端"要拆成两条，各自带公司名）
- 提到家人、伴侣、朋友的关系、职业、所在地也要抽（category=relation，attribute 如"女友_职业"、"女友_所在城市"）
- 提到硬件、语言、工具、模型等技术事实也要抽（attribute 如"电脑配置"、"主要语言"、"推理框架"）
- **模型名、框架名、工具名必须单独成条**（如"常用模型"、"推理框架"），不要塞进"电脑配置"
- **凡是带时间的对话，把时间写进 value**（如"10月20日发现Ollama并发串行"、"9月20日搜狐二面被挂"）
- **关系类除了职业和城市，还要抽共同活动、对方态度**（如"周末和女友一起吃饭"、"女友认为用户太焦虑"）
- **数字、时间点、院校层次（985/211）、薪资、倍速、延迟等精确表述必须原样保留在 value 里**，不要概括成"有提升""考好学校""很慢"
- 没有可抽的内容就输出 []

对话：
{conversation}
"""

CONFLICT_PROMPT = """判断下面两条记忆的关系：

旧记忆：属性「{attr}」，旧值「{old}」，记录于 {old_time}
新记忆：属性「{attr}」，新值「{new}」，记录于 {new_time}

输出 JSON，不要解释：
{{"resolution":"update"或"coexist","reason":"一句话理由"}}

- update：用户**明确否定或替换**了旧值，新值应当替代旧值
- coexist：其余情况一律并存（不同侧面、补充细节、不同对象、不同语境）
- **若两条描述的对象不同（不同公司、不同岗位、不同技术点），必须判 coexist**
- **若新值只是对旧值的补充细节（同一事实的展开），判 coexist，不要覆盖**
- **宁可并存，不要误删：只有当新值直接推翻旧值时才用 update**
"""


def _strip_code_fence(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    return text


def _parse_items(raw):
    cleaned = _strip_code_fence(raw)
    data = json.loads(cleaned)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if not item.get("attribute") or not item.get("value"):
            continue
        cat = item.get("category", "event")
        if cat not in ("identity", "preference", "goal", "relation", "event"):
            cat = "event"
        out.append({
            "subject": str(item.get("subject") or "用户").strip(),
            "attribute": str(item["attribute"]).strip(),
            "value": str(item["value"]).strip(),
            "category": cat,
            "confidence": float(item.get("confidence", 0.8) or 0.8),
        })
    return out


def _dedupe(items):
    """同 attribute 且 value 高度相似视为同一条，保留更长的。"""
    merged = {}
    for it in items:
        key = (it["subject"], it["attribute"])
        prev = merged.get(key)
        if prev is None:
            merged[key] = it
            continue
        a, b = prev["value"], it["value"]
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        # 若短的几乎被长的覆盖，视为同一条
        if shorter[:8] in longer or longer[:8] in shorter:
            merged[key] = it if len(b) > len(a) else prev
        else:
            # 同属性不同侧面：保留两条，用序号区分
            merged[key + (len(merged),)] = it
    return list(merged.values())


def extract(conversation, max_retries=1, samples=2):
    """多次采样取并集，缓解单次抽取漏事实。"""
    prompt = EXTRACT_PROMPT.replace("{conversation}", conversation[:3000])
    pool = []
    for i in range(max(1, samples)):
        temp = 0.0 if i == 0 else 0.3
        for _ in range(max_retries + 1):
            try:
                raw = llm.chat(
                    [{"role": "user", "content": prompt}],
                    temperature=temp,
                    num_predict=900,
                )
                items = _parse_items(raw)
                if items:
                    pool.extend(items)
                    break
            except Exception:
                continue
    return _dedupe(pool)


def judge_conflict(attr, old_value, old_time, new_value, new_time=""):
    """返回 ('update'|'coexist', reason)。失败时默认 update（新的优先）。"""
    prompt = CONFLICT_PROMPT.format(
        attr=attr, old=old_value, old_time=old_time,
        new=new_value, new_time=new_time or "现在",
    )
    raw = llm.chat([{"role": "user", "content": prompt}], temperature=0.0, num_predict=128)
    cleaned = _strip_code_fence(raw)
    try:
        d = json.loads(cleaned)
        res = d.get("resolution", "coexist")
        if res not in ("update", "coexist"):
            res = "coexist"
        return res, d.get("reason", "")
    except Exception:
        return "coexist", "解析失败，默认并存"
