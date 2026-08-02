"""CSV → DB 시딩 (멱등).

products.csv → Product, inventory.csv → Inventory(product_name으로 매칭).
매칭 실패/중복은 조용히 skip하지 않고 집계해 명시적으로 알린다 (Codex 합의).
"""

from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import InfraError
from app.db.models import Inventory, Product


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise InfraError(f"시딩 CSV가 없습니다: {path}")
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def seed_products(db: Session, data_dir: Path | None = None) -> dict:
    """products/inventory CSV를 DB에 시딩한다. 멱등(product_code 기준)."""
    settings = get_settings()
    data_dir = data_dir or settings.DATA_DIR

    products = _read_csv(data_dir / "products.csv")
    inventory = _read_csv(data_dir / "inventory.csv")

    created_products = 0
    for row in products:
        code = row["product_id"].strip()
        exists = db.query(Product).filter(Product.product_code == code).first()
        if exists:
            continue
        db.add(
            Product(
                product_code=code,
                name=row["product_name"].strip(),
                category=row["category"].strip(),
                price=int(row["price"]),
            )
        )
        created_products += 1
    db.commit()

    # 이름 → product 매핑
    name_to_product = {p.name: p for p in db.query(Product).all()}

    # 먼저 전량 검증: unmatched가 있으면 inventory를 하나도 커밋하지 않고 실패
    # (Codex 지적: 부분 반영 방지 — 검증을 commit보다 앞에)
    to_add: list[Inventory] = []
    unmatched: list[str] = []
    for row in inventory:
        pname = row["product_name"].strip()
        product = name_to_product.get(pname)
        if product is None:
            unmatched.append(pname)
            continue
        exists = db.query(Inventory).filter(Inventory.product_id == product.id).first()
        if exists:
            continue
        to_add.append(
            Inventory(
                product_id=product.id,
                stock=int(row["stock"]),
                reorder_level=int(row["reorder_level"]),
                warehouse=row["warehouse"].strip(),
            )
        )

    if unmatched:
        # 조용히 skip하지 않고 명시적 실패 (커밋 전이라 부분 반영 없음)
        db.rollback()
        raise InfraError(f"inventory.csv에 products와 매칭 안 되는 상품: {unmatched}")

    for inv in to_add:
        db.add(inv)
    db.commit()
    created_inv = len(to_add)

    return {
        "products_created": created_products,
        "inventory_created": created_inv,
        "products_total": db.query(Product).count(),
    }
