# -*- coding: utf-8 -*-
"""
clause_detector.py  —  세대·보험사 포맷 차이를 흡수하는 조항 헤더 검출기.

배치 러너(batch_runner.py)와 preprocess.py가 공용으로 쓰는 저수준 모듈.
샘플 14건 분석에서 드러난 포맷 갭을 모두 반영한다:

  1) 제N조(제목)          (표준, 괄호 앞 공백 유무 모두)
  2) 제N조【제목】         (NH생보 본문 주 형식 — 현행 정규식 미탐)
  3) N. (제목) / N-N. (제목)   (DB 다이렉트 번호점 형식 — 현행 정규식 미탐)
  4) 제N조( 뒤 제목이 다음 줄로 넘어가는 경우 (닫는 괄호 미요구)
  5) 상법 제651조 / 제777조 같은 인용의 오탐 필터(시퀀스 기반)
  6) 사업방법서 등 비(非)약관 문서 감지

Windows/PowerShell 환경에서 그대로 실행 가능하며 시스템 의존성 없음
(pymupdf 만 필요).
"""
import re
import unicodedata

# ────────────────────────────────────────────────────────────────────
# 정규식 (모두 '여는 표기'만 매칭 — 제목이 줄바꿈돼도 헤더로 인식)
# ────────────────────────────────────────────────────────────────────
# 제N조( … )  또는  제N조【 … 】  — 앞 공백/전각괄호 허용, 닫힘 불요구
RE_JO = re.compile(r'^제\s*(\d{1,3})\s*조\s*([\(（【\[])\s*(.{0,50})')
# DB 다이렉트: "38. (배당금의 지급)" / "4-1. (보상하지 않는 사항)"
RE_NUM = re.compile(r'^(\d{1,3})(?:-(\d{1,2}))?\.\s*[\(（]\s*(.{1,50})')
# 본문 인용 배제: "제3조에 따라", "제651조의 …", "제N조, 제M조" 등
RE_JOSA = re.compile(r'^제\s*\d{1,3}\s*조\s*[에의를은는이가와과로및·,\)）]')
# 닫는 괄호(제목 마감) 추출용
RE_TITLE_CLOSE = re.compile(r'^(.*?)[\)）】\]]')

# 관/절/장 구조 마커 (DB·삼성 등 계층 표기)
RE_SECTION = re.compile(r'^(제\s*\d{1,2}\s*[관절장편])\s*(.*)')
# 부록·관계법령 경계 마커
RE_APPENDIX = re.compile(r'(부\s*록|관계\s*법령|별\s*표|법령별\s*목차|약관에서\s*인용된)')

# 비약관(사업방법서 등) 시그널 — '가입자 유의사항'은 약관 서문에도 흔하므로 제외
NON_TERMS_SIGNS = ('사업방법서', '사 업 방 법 서', '보험종목의 명칭', '(사업방법서 별지)')

# ────────────────────────────────────────────────────────────────────
# 계층(항/호/목) 표기  —  조 > 항(①) > 호(1. / 가.) > 목(가) / (1))
# ────────────────────────────────────────────────────────────────────
_CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕'
CIRCLED_NUM = {c: i + 1 for i, c in enumerate(_CIRCLED)}
RE_HANG = re.compile(r'^([' + _CIRCLED + r'])\s*(.*)')          # 항: ①②③
RE_HO_NUM = re.compile(r'^(\d{1,2})\.\s*(\S.*)')                # 호: 1. 2.
RE_HO_KOR = re.compile(r'^([가나다라마바사아자차카타파하])\.\s*(\S.*)')  # 호: 가. 나.
RE_HO_PAREN = re.compile(r'^(\d{1,2})\)\s*(\S.*)')             # 호: 1) 2) (DB형)


def match_ho(s):
    """호 표기(1. / 가. / 1)) 매칭 → (라벨, 본문) 또는 None."""
    m = RE_HO_NUM.match(s) or RE_HO_KOR.match(s) or RE_HO_PAREN.match(s)
    return (m.group(1), m.group(2)) if m else None
RE_MOK = re.compile(r'^(?:[\(（](\d{1,2}|[가나다라마바사아자차카타파하])[\)）]'
                    r'|([가나다라마바사아자차카타파하])\))\s*(\S.*)')      # 목: (1)/(가)/가)

# 조 본문에 섞여 들어오는 비(非)조항 블록 마커 → 여기서 조 본문을 끊는다
NONCLAUSE_MARKERS = (
    '쉽게 이해하는 약관 요약서', '약관 요약서', '쉽게 이용할 수 있는 팁',
    '주요내용 요약서', '상품요약서', '보험용어해설', '용어해설',
    '자주 발생하는 민원', '민원 예시', 'QR코드', 'QR 코드',
    '가입자 유의사항', '문답식 상품해설', 'Q & A', 'Q&A',
    '약관을 쉽게', '이 보험계약의 주요내용',
    '약관 이용 가이드북', '가이드북', '기타문의사항', '기타 문의사항',
    '보험금 청구서류', '주요 민원사례',
)


def is_nonclause_marker(s: str) -> bool:
    s2 = s.replace(' ', '')
    return any(m.replace(' ', '') in s2 for m in NONCLAUSE_MARKERS)


def parse_clause_body(body_lines):
    """
    조 본문(헤더 다음 줄부터)을 항 단위로 분해.

    반환: [ {paragraph_no, para_marker, items:[호라벨...], text}, ... ]
      · paragraph_no : 항 번호(정수) — 항 없이 바로 서술이면 None(=조 서두)
      · items         : 해당 항 안에 등장한 호 라벨(중복 없이 순서대로)
    비조항 마커를 만나면 그 지점에서 파싱을 종료(조 경계 오염 차단).
    """
    units = []
    cur = dict(paragraph_no=None, para_marker='', items=[], lines=[])

    def flush():
        if cur['lines']:
            txt = '\n'.join(cur['lines']).strip()
            if txt:
                units.append(dict(paragraph_no=cur['paragraph_no'],
                                  para_marker=cur['para_marker'],
                                  items=cur['items'][:], text=txt))

    for ln in body_lines:
        s = ln.strip()
        if not s:
            continue
        if is_nonclause_marker(s):
            break  # 요약서/간지/팁 등 → 조 본문 종료
        m = RE_HANG.match(s)
        if m:                                   # 새 항 시작
            flush()
            pno = CIRCLED_NUM.get(m.group(1))
            cur = dict(paragraph_no=pno, para_marker=m.group(1),
                       items=[], lines=[s])
            continue
        # 호 표기 수집(항 내부) — 청킹/인용 메타에 활용
        mh = match_ho(s)
        if mh:
            lbl = mh[0]
            if lbl not in cur['items']:
                cur['items'].append(lbl)
        cur['lines'].append(s)
    flush()
    return units

BRACKET_CLOSE = {'(': ')', '（': '）', '【': '】', '[': ']'}


# DB손보 등이 항(①②③) 대신 쓰는 사설영역(PUA) 원문자 글리프 → 표준 원문자 매핑
#   U+F02B1..U+F02C4 == ①..⑳
_PUA_CIRCLED = {chr(0xF02B1 + i): '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'[i]
                for i in range(20)}
_PUA_TABLE = {ord(k): v for k, v in _PUA_CIRCLED.items()}


def normalize(text: str) -> str:
    """NFC 정규화 + PUA 원문자(DB형)를 표준 ①②③ 로 치환."""
    text = unicodedata.normalize('NFC', text)
    if text and any(0xF02B1 <= ord(c) <= 0xF02C4 for c in text):
        text = text.translate(_PUA_TABLE)
    return text


_RE_DUP_TOKEN = re.compile(r'(\b\S{1,12}\b)(\s+\1){2,}')


def collapse_glyph_dup(text: str):
    """
    그림자/겹침 렌더링으로 동일 토큰이 3회 이상 연속 반복되는 추출 아티팩트를
    1회로 축약. (예: '담보종목 담보종목 담보종목 담보종목' → '담보종목')
    반환: (정제텍스트, 발생횟수)
    """
    hits = len(_RE_DUP_TOKEN.findall(text))
    if hits:
        text = _RE_DUP_TOKEN.sub(r'\1', text)
    return text, hits


def clean_line(s: str) -> str:
    """목차 점선/페이지참조 제거 후 좌우 공백 정리."""
    s = s.replace(' ', ' ').strip()
    return s


def is_toc_line(s: str) -> bool:
    """목차 잔해(점선 리더/끝의 페이지번호)인지."""
    return ('···' in s or '···' in s or '...' in s
            or re.search(r'[·.]{4,}', s) is not None
            or re.search(r'[·.]{2,}\s*\d{1,3}\s*$', s) is not None)


def _title_of(bracket: str, rest: str) -> str:
    """여는 괄호 이후 문자열에서 제목만 뽑아냄(닫힘 없으면 통째로, 잘림표시)."""
    m = RE_TITLE_CLOSE.match(rest)
    if m and m.group(1).strip():
        return m.group(1).strip()
    # 같은 줄에 닫힘이 없음 → 제목이 다음 줄로 이어짐
    return (rest.strip() + ' …') if rest.strip() else ''


class ClauseHeader:
    __slots__ = ('kind', 'num', 'sub', 'title', 'page', 'raw', 'title_wrapped')

    def __init__(self, kind, num, sub, title, page, raw, wrapped):
        self.kind = kind          # 'jo' | 'num'
        self.num = num            # 조 번호(정수)
        self.sub = sub            # 부번호(4-1의 1) or None
        self.title = title
        self.page = page
        self.raw = raw
        self.title_wrapped = wrapped

    @property
    def label(self):
        base = f"제{self.num}조" if self.kind == 'jo' else f"{self.num}"
        if self.sub:
            base += f"-{self.sub}"
        return f"{base}({self.title})" if self.title else base

    def __repr__(self):
        return f"<{self.kind} {self.label} p{self.page}>"


def detect_headers(lines, page_map=None, doc_style='auto'):
    """
    줄 목록에서 조항 헤더를 검출. 시퀀스 기반 오탐 필터 포함.

    lines    : [str, ...]  (문서 전체 또는 페이지 연결)
    page_map : lines[i] 가 속한 페이지 번호 리스트(선택)
    doc_style: 'jo' | 'num' | 'auto'  — auto면 두 형식 중 우세한 쪽 선택

    반환: (headers, stats)
      headers : [ClauseHeader,...]  (오탐 제거 후)
      stats   : dict (style, raw_jo, raw_num, accepted, rejected_outlier)
    """
    raw_jo, raw_num = [], []
    for i, ln in enumerate(lines):
        s = clean_line(ln)
        if not s:
            continue
        pg = page_map[i] if page_map else 0
        if RE_JOSA.match(s):
            continue
        m = RE_JO.match(s)
        if m:
            title = _title_of(m.group(2), m.group(3))
            wrapped = (BRACKET_CLOSE.get(m.group(2), ')') not in (m.group(3) or ''))
            raw_jo.append(ClauseHeader('jo', int(m.group(1)),
                                       None, title, pg, s, wrapped))
            continue
        m = RE_NUM.match(s)
        if m and not is_toc_line(s):
            raw_num.append(ClauseHeader('num', int(m.group(1)),
                                        m.group(2), _title_of('(', m.group(3)),
                                        pg, s, ')' not in (m.group(3) or '')))

    # 형식 결정
    if doc_style == 'auto':
        style = 'jo' if len(raw_jo) >= len(raw_num) else 'num'
    else:
        style = doc_style
    raw = raw_jo if style == 'jo' else raw_num

    accepted, rejected = _filter_sequence(raw)
    stats = dict(style=style, raw_jo=len(raw_jo), raw_num=len(raw_num),
                 accepted=len(accepted), rejected_outlier=rejected)
    return accepted, stats


def _filter_sequence(headers, max_jump=15, abs_cap=150):
    """
    시퀀스 기반 오탐 제거.
      - 조 번호는 특약이 바뀌면 1로 리셋될 수 있음 → 하향 리셋 허용.
      - 직전 승인값 대비 +max_jump 초과로 튀는 고립 번호는 인용(예: 상법 제651조)
        으로 보고 제거.
      - 절대 상한(abs_cap) 초과는 무조건 제거.
    """
    accepted = []
    rejected = 0
    prev = 0
    for h in headers:
        n = h.num
        if n > abs_cap:
            rejected += 1
            continue
        if not accepted:
            accepted.append(h); prev = n; continue
        if n <= prev:                      # 리셋/동일(특약 경계 등) → 허용
            accepted.append(h); prev = n
        elif n - prev <= max_jump:          # 정상 증가
            accepted.append(h); prev = n
        else:                               # 큰 점프 → 인용 오탐
            rejected += 1
    return accepted, rejected


def looks_like_non_terms(first_pages_text: str) -> bool:
    """앞부분 텍스트로 사업방법서/요약서 등 비약관 문서 판별."""
    head = first_pages_text[:3000]
    hits = sum(1 for sign in NON_TERMS_SIGNS if sign in head)
    return hits >= 1
