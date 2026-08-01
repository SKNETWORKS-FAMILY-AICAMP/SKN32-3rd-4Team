"""환불·교환·반품 운영 정책 PDF 생성기 (RAG 소스 문서).

브랜드명을 config 단일 소스(`app.core.config.BRAND_NAME`)에서 읽어 문서를 재생성한다.
사실(기간·배송비·조항 번호 등)은 고정이며 브랜드/법인명만 변수화했다. 브랜드가 바뀌면
이 스크립트를 다시 실행(`python -m scripts.gen_policy_pdf`)한 뒤 `scripts.manage ingest`로
벡터 인덱스를 재빌드하면 RAG 응답에도 새 브랜드가 반영된다.

한글은 시스템 폰트(맑은 고딕)를 임베딩한다 — 폰트가 없으면 조용히 깨진 글자로 만들지 않고
명시적으로 실패한다(무폴백).
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
OUT_PDF = ROOT / "data" / "docs" / "환불교환정책.pdf"

def _register_fonts() -> tuple[str, str]:
    s = get_settings()
    reg, bold = s.PDF_FONT_REGULAR, s.PDF_FONT_BOLD
    if not reg.exists() or not bold.exists():
        raise SystemExit(
            f"한글 폰트를 찾을 수 없습니다: {reg} / {bold}. "
            "config PDF_FONT_REGULAR/BOLD 경로를 수정하세요."
        )
    pdfmetrics.registerFont(TTFont("Malgun", str(reg)))
    pdfmetrics.registerFont(TTFont("MalgunBd", str(bold)))
    return "Malgun", "MalgunBd"


def build() -> None:
    brand = get_settings().BRAND_NAME
    # 법인 표기: 브랜드에서 파생(합성 데모 — 실제 법인 아님).
    corp_ko = f"(주){brand}"
    corp_en = "BAROBOM COMMERCE"

    reg, bold = _register_fonts()
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontName=reg, fontSize=9.5, leading=15)
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontName=bold, fontSize=17, leading=22)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=bold, fontSize=11.5, leading=17,
                        spaceBefore=8, spaceAfter=3)
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.grey)

    def _table(data: list[list[str]], col_widths: list[float]) -> Table:
        t = Table(data, colWidths=col_widths, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), reg),
            ("FONTNAME", (0, 0), (-1, 0), bold),
            ("FONTSIZE", (0, 0), (-1, -1), 8.7),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f3640")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b2bec3")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f6fa")]),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    story: list = []
    story.append(Paragraph(f"{corp_ko}  {corp_en}", small))
    story.append(Paragraph("환불·교환·반품 운영 정책", h1))
    story.append(Paragraph(f"Return, Exchange &amp; Refund Policy — {brand} 고객지원본부", body))
    story.append(Spacer(1, 6))

    story.append(_table([
        ["항목", "내용", "항목", "내용"],
        ["문서번호", "CS-POL-2026-014", "제·개정일", "2026-05-01"],
        ["관리부서", "고객지원본부", "시행일", "2026-05-15"],
        ["문서등급", "대외 공개", "버전", "v3.2"],
    ], [28 * mm, 55 * mm, 28 * mm, 45 * mm]))
    story.append(Spacer(1, 8))

    story.append(Paragraph(
        f"본 정책은 「전자상거래 등에서의 소비자보호에 관한 법률」에 근거하여 {brand}(이하 '회사')이 "
        "판매하는 상품의 환불·교환·반품 처리 기준을 정한다.", body))

    story.append(Paragraph("제1조 (청약철회 기간)", h2))
    story.append(Paragraph(
        "고객은 다음 각 호의 기간 내에 청약철회(반품)를 신청할 수 있다. 사유별 적용 기간은 아래 표와 같다.", body))
    story.append(Spacer(1, 3))
    story.append(_table([
        ["반품 사유", "신청 가능 기간", "배송비 부담", "비고"],
        ["단순 변심", "수령일로부터 7일 이내", "고객", "재판매 가능 상태 유지 시"],
        ["상품 불량·하자", "수령일로부터 30일 이내", "회사", "사진 첨부 권장"],
        ["오배송(상품 상이)", "수령일로부터 30일 이내", "회사", "즉시 회수 처리"],
        ["표시·광고와 상이", "수령 후 3개월 또는 인지 후 30일", "회사", "관련법 기준"],
    ], [32 * mm, 48 * mm, 22 * mm, 42 * mm]))

    story.append(Paragraph("제2조 (반품 배송비)", h2))
    story.append(Paragraph(
        "단순 변심에 의한 반품의 왕복 배송비는 고객이 부담하며, 상품 불량·오배송의 경우 전액 회사가 "
        "부담한다. 도서·산간 지역은 추가 배송비가 발생할 수 있다.", body))
    story.append(Spacer(1, 3))
    story.append(_table([
        ["구분", "편도", "왕복", "비고"],
        ["일반 지역", "3,000원", "6,000원", "기본 요율"],
        ["제주 지역", "5,000원", "10,000원", "추가 4,000원"],
        ["도서·산간", "6,500원", "13,000원", "추가 7,000원"],
    ], [32 * mm, 30 * mm, 30 * mm, 42 * mm]))

    story.append(Paragraph("제3조 (환불 처리 기간)", h2))
    story.append(Paragraph(
        "반품 상품의 회수·검수가 완료된 후 결제수단별로 아래 기간 내에 환불을 진행한다. 카드 취소 "
        "반영 시점은 카드사 사정에 따라 달라질 수 있다.", body))
    story.append(Spacer(1, 3))
    story.append(_table([
        ["결제수단", "환불 방식", "소요 기간(영업일)"],
        ["신용·체크카드", "승인 취소", "검수 후 3일 + 카드사 3~5일"],
        ["계좌이체·무통장", "계좌 환급", "검수 후 3일 이내"],
        ["적립금·쿠폰", "즉시 복원", "검수 후 1일 이내"],
        ["간편결제(페이)", "결제 취소", "검수 후 2~4일"],
    ], [38 * mm, 34 * mm, 62 * mm]))

    story.append(Paragraph("제4조 (교환 절차)", h2))
    story.append(Paragraph(
        "사이즈·색상 교환은 동일 상품의 재고가 있는 경우에 한해 가능하다. 마이페이지 &gt; 주문내역 &gt; "
        "교환신청에서 접수하며, 교환 배송비 정책은 제2조 반품 배송비 기준을 준용한다.", body))

    story.append(Paragraph("제5조 (환불·교환 불가 사유)", h2))
    story.append(Paragraph(
        "다음 각 호의 어느 하나에 해당하는 경우 환불·교환이 제한된다. (1) 고객의 책임 있는 사유로 "
        "상품이 멸실·훼손된 경우 (2) 사용 또는 일부 소비로 상품 가치가 현저히 감소한 경우 (3) 시간 "
        "경과로 재판매가 곤란한 경우 (4) 복제 가능한 상품의 포장을 훼손한 경우 (5) 식품 등 신선·위생 "
        "상품을 개봉한 경우.", body))

    story.append(Paragraph("제6조 (문의처)", h2))
    story.append(Paragraph(
        "환불·교환 관련 문의는 고객센터(1588-0000, 평일 09:00~18:00) 또는 앱 내 1:1 문의로 접수한다.", body))

    story.append(Paragraph("부칙 — 개정 이력", h2))
    story.append(_table([
        ["버전", "개정일", "주요 변경 내용"],
        ["v3.2", "2026-05-01", "결제수단별 환불기간 표 신설, 제주/도서산간 배송비 명시"],
        ["v3.1", "2025-11-10", "표시·광고 상이 시 청약철회 기간 보강"],
        ["v3.0", "2025-03-02", "전면 개정(조항 체계 도입)"],
    ], [22 * mm, 28 * mm, 84 * mm]))

    def _footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(reg, 7.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(20 * mm, 12 * mm, f"{corp_ko}  {corp_en}  ·  CS-POL-2026-014  ·  대외 공개 · 무단 배포 금지")
        canvas.drawRightString(190 * mm, 12 * mm, f"- {doc.page} -")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(OUT_PDF), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=20 * mm,
        title="환불·교환·반품 운영 정책", author=corp_ko,
    )
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    print(f"[gen_policy_pdf] 생성 완료: {OUT_PDF} (브랜드: {brand})")


if __name__ == "__main__":
    build()
