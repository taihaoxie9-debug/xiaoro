from __future__ import annotations

from app.guide.retrieval.product_evidence_assets import (
    ProductEvidenceAssets,
    ProductEvidenceBlock,
    ProductEvidenceManifest,
    product_evidence_id,
)
from app.guide.retrieval.product_evidence_reader import (
    ProductEvidenceReader,
)
from app.guide.retrieval.product_evidence_retrieval import (
    EvidenceQuery,
    ProductEvidenceRetriever,
    prepare_evidence_search,
)


def test_evidence_query_carries_no_raw_request_text_or_source_spans() -> None:
    assert "raw_question" not in EvidenceQuery.model_fields
    assert "question_meaning" not in EvidenceQuery.model_fields
    assert "product_mention_spans" not in EvidenceQuery.model_fields


def _query(
    *,
    product_ids: tuple[int, ...],
    raw_question: str,
    question_meaning: str,
    safety_sensitive: bool,
    product_mention_spans: tuple[tuple[int, int], ...] = (),
    product_identity_names: tuple[str, ...] = (),
) -> EvidenceQuery:
    return EvidenceQuery(
        product_ids=product_ids,
        search=prepare_evidence_search(
            source_text=raw_question,
            question_meaning=question_meaning,
            product_mention_spans=product_mention_spans,
        ),
        safety_sensitive=safety_sensitive,
        product_identity_names=product_identity_names,
    )


def _source(product_id: int, index: int) -> dict[str, object]:
    source_sha = f"{product_id:064x}"[-64:]
    image_sha = f"{product_id * 100 + index:064x}"[-64:]
    return {
        "source_file": f"detail_{product_id}_ocr.json",
        "source_sha256": source_sha,
        "image_file": f"{index:03d}.jpg",
        "image_index": index,
        "image_sha256": image_sha,
        "source_locator": (
            "urn:xiaoro:product-detail-image:"
            f"pid:{product_id}:source-sha256:{source_sha}:"
            f"image-sha256:{image_sha}"
        ),
        "source_url": f"https://example.com/{product_id}/{index}.jpg",
        "recovery_status": "source_record",
        "resolved_image_file": f"{index:03d}.jpg",
        "image_region": [0, 0, 790, 1000],
    }


def _block(
    *,
    product_id: int,
    index: int,
    label: str,
    exact_text: str,
    meaning: str,
    descriptors: list[str] | None = None,
    subject_scope: str = "exact_product",
    variant_scope: str | None = None,
    relations: list[dict[str, str]] | None = None,
    disclaimer: str | None = None,
    hard_filter: bool = False,
) -> ProductEvidenceBlock:
    forbidden = ["safety_guarantee"]
    if not hard_filter:
        forbidden.append("hard_filter")
    if label == "consumer_self_report":
        forbidden.append("clinical_effectiveness")
    payload: dict[str, object] = {
        "product_id": product_id,
        "subject_scope": subject_scope,
        "variant_scope": variant_scope,
        "management_label": label,
        "transcription_basis": "visual_transcription",
        "exact_text": exact_text,
        "plain_meaning": meaning,
        "relations": relations or [],
        "qualifiers": {
            "sample_size": 35 if label == "consumer_self_report" else None,
            "population": (
                "敏感肌消费者"
                if label == "consumer_self_report"
                else None
            ),
            "method": (
                "消费者自评"
                if label == "consumer_self_report"
                else None
            ),
            "baseline": None,
            "duration": None,
            "disclaimer": (
                disclaimer
                or (
                    "实际结果因人而异"
                    if label == "consumer_self_report"
                    else None
                )
            ),
            "footnotes": [],
        },
        "free_descriptors": descriptors or [],
        "review_status": "accepted",
        "allowed_uses": [
            "answer",
            "display",
            *(
                ["compare", "hard_filter"]
                if hard_filter
                else []
            ),
        ],
        "forbidden_uses": forbidden,
        "review_rationale": "检索测试证据。",
        "selection_review": {
            "decision": "answer_only",
            "visual_confirmed": True,
            "rationale": "检索夹具只验证回答召回，不授权选择用途。",
            "projections": [],
        },
        "source": _source(product_id, index),
        "supporting_sources": [],
    }
    return ProductEvidenceBlock.model_validate(
        {
            "evidence_id": product_evidence_id(payload),
            **payload,
        },
        strict=True,
    )


def _reader() -> ProductEvidenceReader:
    blocks = tuple(
        sorted(
            [
                _block(
                    product_id=78,
                    index=0,
                    label="consumer_self_report",
                    exact_text=(
                        "100%消费者认同膜布轻薄服帖；"
                        "100%消费者认同膜布不易滑落"
                    ),
                    meaning="消费者认为膜布服帖并且不容易滑落。",
                    descriptors=["服帖", "不易滑落"],
                ),
                _block(
                    product_id=78,
                    index=1,
                    label="merchant_cited_test",
                    exact_text="皮肤红区面积降低49.5%，皮肤温度降低4.8℃",
                    meaning="商家引用测试称可改善泛红和肌肤灼热。",
                    descriptors=["泛红", "灼热"],
                ),
                _block(
                    product_id=78,
                    index=2,
                    label="packaging_information",
                    exact_text="新老包装随机发货，产品功效及成分不变",
                    meaning="收到的包装可能与图片不同，因为正在换包装。",
                    descriptors=[],
                ),
                _block(
                    product_id=78,
                    index=3,
                    label="safety_transcript",
                    exact_text="适合敏感肌及特殊美容项目后使用",
                    meaning="商家宣称适合敏感肌和特殊美容项目后使用。",
                    descriptors=["敏感肌", "特殊美容项目后"],
                ),
                _block(
                    product_id=34,
                    index=0,
                    label="usage",
                    exact_text="维生素CE修护精华液位于护肤第四步",
                    meaning="商家建议将CE精华用于护肤第四步。",
                    descriptors=["护肤第四步"],
                ),
                _block(
                    product_id=120,
                    index=0,
                    label="merchant_claim",
                    exact_text="天猫国际100%官方直采，英国原装进口",
                    meaning=(
                        "页面将所示白瓶香水描述为天猫国际官方直采"
                        "和英国原装进口。"
                    ),
                    descriptors=[
                        "天猫国际官方直采宣传",
                        "英国原装进口宣传",
                    ],
                    subject_scope="exact_variant",
                    variant_scope="天猫国际页面所示30ml版本",
                    relations=[
                        {
                            "subject": "天猫国际页面所示祖玛珑香水",
                            "predicate": "merchant_channel_claim",
                            "object": "100%官方直采、英国原装进口宣传",
                        }
                    ],
                    disclaimer=(
                        "渠道宣传不能替代对用户收到单件商品的"
                        "官方鉴真，也不外推到其他店铺"
                    ),
                ),
                _block(
                    product_id=120,
                    index=1,
                    label="faq",
                    exact_text=(
                        "商家FAQ称新香水刚喷时可能有较浓烈酒精味，"
                        "等待几分钟让酒精挥发后再闻中后调"
                    ),
                    meaning=(
                        "商家把刚喷时的刺鼻感解释为酒精载体"
                        "尚未挥发，并建议等待几分钟再闻。"
                    ),
                    descriptors=[
                        "新开封酒精味FAQ",
                        "等待几分钟再闻",
                    ],
                    relations=[
                        {
                            "subject": "刚喷时酒精味较浓",
                            "predicate": "merchant_faq_answer",
                            "object": "等待几分钟挥发后再闻",
                        }
                    ],
                    disclaimer=(
                        "这是商家一般性解释；气味异常不能单独判断"
                        "真伪或品质，若出现刺激、呼吸不适或皮肤"
                        "反应应停止接触"
                    ),
                ),
                _block(
                    product_id=120,
                    index=2,
                    label="packaging_information",
                    exact_text=(
                        "另一张买家实拍展示JO MALONE LONDON "
                        "ENGLISH PEAR & FREESIA COLOGNE包装与瓶身标签"
                    ),
                    meaning=(
                        "另一张不同视角的买家照片辅助确认"
                        "英国梨与小苍兰包装文字。"
                    ),
                    descriptors=[
                        "瓶身标签",
                        "第二张买家包装实拍",
                        "英国梨与小苍兰包装",
                    ],
                    subject_scope="exact_variant",
                    variant_scope="买家照片所示包装",
                    relations=[
                        {
                            "subject": "买家照片所示祖玛珑香水",
                            "predicate": "observed_package_label",
                            "object": (
                                "English Pear & Freesia Cologne包装文字"
                            ),
                        }
                    ],
                    disclaimer=(
                        "只绑定照片所示单件包装，不能据此判断"
                        "新老包装、容量或真伪"
                    ),
                ),
                _block(
                    product_id=143,
                    index=0,
                    label="packaging_information",
                    exact_text=(
                        "成分：乙醇、水、香精、丁基甲氧基二苯"
                        "甲酰基甲烷；其他微量成分：CI 19140、"
                        "CI 15985、CI 17200、CI 14700"
                    ),
                    meaning="中文标签列出基础配方和四种微量色料。",
                    descriptors=[
                        "CI14700",
                        "CI15985",
                        "CI17200",
                        "CI19140",
                        "乙醇",
                        "水",
                        "阿伏苯宗",
                        "香精",
                    ],
                    subject_scope="exact_variant",
                    variant_scope="中文标签所示100ml经典版本",
                    relations=[
                        {
                            "subject": "香奈儿五号香水（经典）",
                            "predicate": "label_ingredient_list",
                            "object": (
                                "乙醇、水、香精、丁基甲氧基二苯"
                                "甲酰基甲烷及四种CI色料"
                            ),
                        }
                    ],
                    disclaimer=(
                        "成分存在不等于个体安全；配方可能随批次"
                        "变化，应核对实物标签"
                    ),
                ),
                _block(
                    product_id=143,
                    index=1,
                    label="product_specification",
                    exact_text=(
                        "产品中文名称：香奈儿五号香水（经典）；"
                        "净含量100ml；原产国法国；备案号"
                        "国妆网备进字（沪）2020009314"
                    ),
                    meaning="中文标签给出正式名、容量、原产国和备案号。",
                    descriptors=[
                        "100ml",
                        "备案号2020009314",
                        "法国",
                        "香奈儿五号香水经典",
                    ],
                    subject_scope="exact_variant",
                    variant_scope="中文标签所示100ml经典版本",
                    relations=[
                        {
                            "subject": "香奈儿五号香水（经典）",
                            "predicate": "label_net_content",
                            "object": "100ml",
                        },
                        {
                            "subject": "香奈儿五号香水（经典）",
                            "predicate": "label_country_of_origin",
                            "object": "法国",
                        },
                        {
                            "subject": "香奈儿五号香水（经典）",
                            "predicate": "label_filing_number",
                            "object": "国妆网备进字（沪）2020009314",
                        },
                    ],
                    disclaimer=(
                        "批号和限期使用日期见实物包装，具体信息"
                        "以收到实物为准"
                    ),
                    hard_filter=True,
                ),
                _block(
                    product_id=143,
                    index=2,
                    label="product_specification",
                    exact_text="N°5 CHANEL PARIS EAU DE PARFUM",
                    meaning="主商品瓶身和外盒明确显示五号淡香精EDP浓度。",
                    descriptors=[
                        "EDP",
                        "Eau de Parfum",
                        "经典瓶身",
                        "香奈儿五号",
                    ],
                    subject_scope="exact_variant",
                    variant_scope="中文标签所示100ml经典版本",
                    relations=[
                        {
                            "subject": "N°5 CHANEL",
                            "predicate": (
                                "observed_package_concentration"
                            ),
                            "object": "Eau de Parfum（EDP）",
                        }
                    ],
                    disclaimer=(
                        "本图未显示可靠容量，100ml由中文标签另证；"
                        "不得与PARFUM浓香精版本混同"
                    ),
                ),
                _block(
                    product_id=143,
                    index=3,
                    label="product_specification",
                    exact_text=(
                        "N°5 CHANEL PARIS EAU DE PARFUM "
                        "VAPORISATEUR SPRAY，35ml / 1.2 fl. oz."
                    ),
                    meaning="买家照片明确支持35ml喷雾EDP变体。",
                    descriptors=["N°5 EDP 35ml", "买家35ml包装"],
                    subject_scope="exact_variant",
                    variant_scope="买家照片所示N°5 EDP 35ml喷雾",
                    relations=[
                        {
                            "subject": "买家照片所示N°5 EDP喷雾",
                            "predicate": "observed_package_net_content",
                            "object": "35ml / 1.2 fl. oz.",
                        }
                    ],
                    disclaimer=(
                        "35ml只绑定买家照片所示变体，"
                        "不能改写当前中文标签100ml SKU"
                    ),
                    hard_filter=True,
                ),
                _block(
                    product_id=143,
                    index=4,
                    label="packaging_information",
                    exact_text=(
                        "买家实拍可见N°5 EAU DE PARFUM瓶身和外盒"
                    ),
                    meaning=(
                        "买家照片支持EDP浓度和包装外观，"
                        "但不支持容量。"
                    ),
                    descriptors=["买家EDP实拍"],
                    subject_scope="exact_variant",
                    variant_scope="买家照片所示EDP包装",
                    relations=[
                        {
                            "subject": "买家照片所示N°5",
                            "predicate": "observed_package_appearance",
                            "object": "EAU DE PARFUM瓶身和外盒",
                        }
                    ],
                    disclaimer=(
                        "照片未清晰显示容量，不能据此判断100ml"
                    ),
                ),
                _block(
                    product_id=80,
                    index=0,
                    label="merchant_claim",
                    exact_text=(
                        "阿玛尼权力PRO粉底液，高定绒雾妆，"
                        "轻盈高遮瑕"
                    ),
                    meaning=(
                        "商家将权力PRO粉底液定位为轻盈、"
                        "高遮瑕和高定绒雾妆效。"
                    ),
                    descriptors=[
                        "权力PRO粉底液",
                        "轻盈高遮瑕",
                        "高定绒雾妆",
                    ],
                ),
                _block(
                    product_id=80,
                    index=1,
                    label="product_specification",
                    exact_text=(
                        "新旧色号比对：新#1.5对应经典#1.5；"
                        "新#2对应经典#2；新#3对应经典#3"
                    ),
                    meaning=(
                        "页面给出Power Fabric Pro与经典权力PLUS"
                        "的色号转换关系。"
                    ),
                    descriptors=["新旧色号比对"],
                    variant_scope=(
                        "Power Fabric Pro与经典权力PLUS色号对照"
                    ),
                    relations=[
                        {
                            "subject": "新#2",
                            "predicate": "merchant_shade_correspondence",
                            "object": "经典#2",
                        }
                    ],
                ),
                _block(
                    product_id=115,
                    index=0,
                    label="product_specification",
                    exact_text=(
                        "迪奥烈艳蓝金唇膏提供全新绒雾、"
                        "丝绒哑光和经典缎光三种妆效、"
                        "32款高订色泽；999归入红色系"
                    ),
                    meaning=(
                        "页面给出产品族的三种妆效、32款色泽"
                        "和色系分类，并把999列在红色系。"
                    ),
                    descriptors=[
                        "32款高订色泽",
                        "999红色系",
                        "三大妆效",
                    ],
                    subject_scope="exact_product",
                    variant_scope="迪奥烈艳蓝金唇膏产品族",
                    relations=[
                        {
                            "subject": "迪奥烈艳蓝金唇膏",
                            "predicate": "merchant_finish_options",
                            "object": "全新绒雾、丝绒哑光、经典缎光",
                        },
                        {
                            "subject": "999",
                            "predicate": "merchant_shade_family",
                            "object": "红色系",
                        },
                    ],
                    disclaimer=(
                        "OCR未可靠读取全部32款色号名称，只保存"
                        "图中能确认的妆效、总数、色系和999归类"
                    ),
                ),
                _block(
                    product_id=115,
                    index=1,
                    label="product_specification",
                    exact_text="999丝绒",
                    meaning="明星色号页明确展示999丝绒变体。",
                    descriptors=["999丝绒"],
                    subject_scope="exact_variant",
                    variant_scope="999丝绒",
                    relations=[
                        {
                            "subject": "999",
                            "predicate": "merchant_shade_finish",
                            "object": "丝绒妆效",
                        }
                    ],
                ),
                _block(
                    product_id=67,
                    index=0,
                    label="safety_transcript",
                    exact_text=(
                        "商家称细软颗粒不会对皮肤或健康造成"
                        "伤害或风险，且产品经过安全检测审核"
                    ),
                    meaning="商家给出无健康风险的安全陈述。",
                    descriptors=[
                        "安全检测审核宣传",
                        "无健康风险商家宣称",
                    ],
                ),
                _block(
                    product_id=67,
                    index=1,
                    label="consumer_self_report",
                    exact_text="87%消费者认可提亮肌肤",
                    meaning="87%是消费者对提亮肌肤的主观认可。",
                    descriptors=["87%提亮认可", "消费者焕亮认同"],
                    relations=[
                        {
                            "subject": "提亮肌肤",
                            "predicate": "consumer_agrees",
                            "object": "87%认可",
                        }
                    ],
                    disclaimer=(
                        "主观认可不是客观肤色仪器测试；"
                        "实际结果因人而异"
                    ),
                ),
                _block(
                    product_id=117,
                    index=0,
                    label="product_specification",
                    exact_text=(
                        "牛郎色 / SPACE COWBOY；备案名"
                        "URBAN DECAY MOONDUST月耀星眸"
                        "单色眼影银河牛仔"
                    ),
                    meaning="页面给出牛郎色的正式备案身份。",
                    descriptors=["牛郎色", "银河牛仔"],
                    subject_scope="exact_variant",
                    variant_scope="牛郎色",
                ),
                _block(
                    product_id=117,
                    index=1,
                    label="merchant_claim",
                    exact_text="茶牛郎色：清冷小白花妆",
                    meaning="商家把茶牛郎色用于清冷小白花妆参考。",
                    descriptors=[
                        "清冷小白花妆",
                        "茶牛郎上眼参考",
                    ],
                    subject_scope="exact_variant",
                    variant_scope="茶牛郎色",
                ),
                _block(
                    product_id=117,
                    index=2,
                    label="merchant_claim",
                    exact_text="冰织女：万能叠涂冰透爆闪",
                    meaning="商家把冰织女色号用于叠涂爆闪妆容。",
                    descriptors=[
                        "万能叠涂",
                        "冰织女上眼参考",
                    ],
                    subject_scope="exact_variant",
                    variant_scope=(
                        "冰织女 / COSMIC COWGIRL / 星际牧女"
                    ),
                ),
                _block(
                    product_id=117,
                    index=3,
                    label="product_specification",
                    exact_text=(
                        "茶牛郎 / CRUSHIN' HARD；备案名"
                        "URBAN DECAY MOONDUST月耀星眸"
                        "单色眼影坠落银河"
                    ),
                    meaning="页面给出茶牛郎色的正式备案身份。",
                    descriptors=[
                        "CRUSHIN' HARD",
                        "坠落银河",
                        "茶牛郎",
                    ],
                    subject_scope="exact_variant",
                    variant_scope=(
                        "茶牛郎 / CRUSHIN' HARD / 坠落银河"
                    ),
                ),
                _block(
                    product_id=57,
                    index=0,
                    label="merchant_claim",
                    exact_text=(
                        "页面将产品用于晒黑晒伤、晒后干燥、分界线、"
                        "粗糙起皮、油腻搓泥和流汗失效等防晒问题"
                    ),
                    meaning=(
                        "商家以多类防晒和肤感问题引出对水润、"
                        "防水防汗高倍防晒的需求。"
                    ),
                    descriptors=[
                        "晒后干燥",
                        "晒黑晒伤",
                        "流汗失效问题",
                        "粗糙起皮",
                    ],
                    relations=[
                        {
                            "subject": (
                                "晒黑晒伤、干燥、油腻搓泥和流汗场景"
                            ),
                            "predicate": "merchant_positions_for",
                            "object": "高倍防水防汗、清爽水润",
                        }
                    ],
                    disclaimer=(
                        "这是问题场景与产品定位，不是每项问题"
                        "均经独立测试解决"
                    ),
                ),
                _block(
                    product_id=57,
                    index=1,
                    label="merchant_claim",
                    exact_text=(
                        "页面将高倍防水防汗防晒定位于城市运动、"
                        "海边游玩、徒步露营和校园军训场景"
                    ),
                    meaning=(
                        "商家列出多种户外活动作为产品的"
                        "高倍防水防汗使用场景。"
                    ),
                    descriptors=[
                        "城市运动防晒",
                        "徒步露营",
                        "校园军训",
                        "海边游玩",
                        "防水防汗宣传",
                    ],
                    relations=[
                        {
                            "subject": "碧柔水活防晒水润凝蜜",
                            "predicate": "merchant_positions_for",
                            "object": "城市运动、海边、徒步和军训",
                        }
                    ],
                    disclaimer=(
                        "场景宣传不表示不需补涂；80分钟浴后"
                        "SPF50+测试是具体耐水条件"
                    ),
                ),
            ],
            key=lambda item: item.evidence_id,
        )
    )
    manifest = ProductEvidenceManifest.model_construct(
        schema_version="product-evidence-v1",
        asset_id="guide-product-evidence-v1",
        asset_version="test",
        evidence_file="test.jsonl",
        evidence_sha256="1" * 64,
        audit_file="audit.jsonl",
        audit_sha256="2" * 64,
        evidence_count=len(blocks),
        product_count=len(
            {block.product_id for block in blocks}
        ),
        image_count=len(blocks),
        status_counts={"accepted": len(blocks)},
        allowed_use_counts={
            "answer": len(blocks),
            "display": len(blocks),
        },
        manifest_sha256="3" * 64,
    )
    assets = ProductEvidenceAssets.model_construct(
        manifest=manifest,
        evidence=blocks,
        audit=(),
    )
    return ProductEvidenceReader(assets)


def test_indirect_slippage_question_uses_meaning_not_fixed_tag() -> None:
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(78,),
            raw_question="它那个布会不会老往下掉？",
            question_meaning="询问面膜是否服帖、是否容易滑落",
            safety_sensitive=False,
        )
    )

    assert packet.selected
    assert "不易滑落" in packet.selected[0].evidence.exact_text
    assert packet.selected[0].evidence.product_id == 78


def test_ungrounded_question_meaning_cannot_nominate_evidence_alone() -> None:
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(78,),
            raw_question="这款整体怎么样？",
            question_meaning="询问面膜是否服帖、是否容易滑落",
            safety_sensitive=False,
        )
    )

    assert packet.selected == ()
    assert packet.missing_aspects


def test_confirmed_product_name_span_does_not_pollute_relevance() -> None:
    product_name = "新老包装随机发货产品功效成分不变"
    raw_question = f"{product_name}那个布会不会老往下掉？"
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(78,),
            raw_question=raw_question,
            question_meaning="询问面膜是否服帖、是否容易滑落",
            safety_sensitive=False,
            product_mention_spans=((0, len(product_name)),),
        )
    )

    assert not (
        set(packet.query.search.product_mention_features)
        & set(packet.query.search.combined_features)
    )
    assert "不易滑落" in packet.selected[0].evidence.exact_text


def test_red_hot_face_paraphrase_selects_test_with_qualifiers() -> None:
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(78,),
            raw_question="我脸红得跟着火一样，这个能干嘛？",
            question_meaning="询问对泛红和肌肤灼热的相关证据",
            safety_sensitive=False,
        )
    )

    assert packet.selected[0].evidence.management_label == (
        "merchant_cited_test"
    )
    assert "49.5%" in packet.selected[0].evidence.exact_text


def test_packaging_question_works_without_free_descriptor() -> None:
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(78,),
            raw_question="收到的怎么和图片长得不一样？",
            question_meaning="询问收到的商品包装与页面图片不同",
            safety_sensitive=False,
        )
    )

    assert packet.selected[0].evidence.management_label == (
        "packaging_information"
    )


def test_direct_faq_outranks_broad_variant_overlap() -> None:
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(120,),
            raw_question="刚喷为什么一股酒精味？",
            question_meaning="询问新香水初喷酒精味的原因",
            safety_sensitive=False,
        )
    )

    assert packet.selected[0].evidence.management_label == "faq"
    assert "等待几分钟" in packet.selected[0].evidence.exact_text


def test_product_name_repeated_in_meaning_does_not_outrank_faq() -> None:
    product_name = "祖玛珑英国梨与小苍兰"
    raw_question = f"{product_name}刚喷为什么一股酒精味？"
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(120,),
            raw_question=raw_question,
            question_meaning=(
                "为什么刚喷祖玛珑英国梨与小苍兰香水时会有酒精味？"
            ),
            safety_sensitive=False,
            product_mention_spans=((0, len(product_name)),),
        )
    )

    assert packet.selected[0].evidence.management_label == "faq"
    assert "等待几分钟" in packet.selected[0].evidence.exact_text


def test_canonical_identity_is_removed_from_translated_meaning() -> None:
    canonical_name = (
        "阿玛尼权力持妆PRO粉底液#2 暖调白皙30ml遮瑕控油"
    )
    overextended_mention = (
        "阿玛尼（ARMANI）权力持妆PRO粉底液#2 "
        "暖调白皙30ml遮瑕控油新版2号"
    )
    raw_question = f"{overextended_mention}对应老版哪个色号？"
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(80,),
            raw_question=raw_question,
            question_meaning=(
                "用户想知道阿玛尼权力持妆PRO粉底液"
                "新版2号对应老版的哪个色号。"
            ),
            safety_sensitive=False,
            product_mention_spans=((0, len(overextended_mention)),),
            product_identity_names=(canonical_name,),
        )
    )

    assert "新#2对应经典#2" in packet.selected[0].evidence.exact_text
    assert packet.ambiguity_reasons == ()


def test_confirmed_variant_scope_does_not_promote_product_family() -> None:
    product_name = "迪奥烈艳蓝金唇膏 丝绒 999"
    raw_question = f"{product_name}到底是什么妆效？"
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(115,),
            raw_question=raw_question,
            question_meaning="询问999色号的妆效",
            safety_sensitive=False,
            product_mention_spans=((0, len(product_name)),),
            product_identity_names=(product_name,),
        )
    )

    assert packet.selected[0].evidence.subject_scope == "exact_variant"
    assert packet.selected[0].evidence.exact_text == "999丝绒"


def test_one_character_descriptor_cannot_dominate_capacity_question() -> None:
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(143,),
            raw_question="经典五号这瓶多大？",
            question_meaning="询问香水容量规格",
            safety_sensitive=False,
        )
    )

    assert "100ml" in packet.selected[0].evidence.exact_text
    assert any(
        "35ml" in item.evidence.exact_text
        for item in packet.selected
    )
    assert packet.ambiguity_reasons == (
        "这款有多个容量规格变体："
        "中文标签所示100ml经典版本为100ml；"
        "买家照片所示N°5 EDP 35ml喷雾为35ml / 1.2 fl. oz.。"
        "购买前请核对所选或收到的具体规格。",
    )


def test_explicit_variant_inside_product_mention_selects_that_variant_without_ambiguity(
) -> None:
    mention = "香奈儿五号香水经典花香调 35ml"
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(143,),
            raw_question=f"{mention} 是多大？",
            question_meaning="询问香奈儿五号香水经典花香调 35ml 的容量规格",
            safety_sensitive=False,
            product_mention_spans=((0, len(mention)),),
            product_identity_names=(mention,),
        )
    )

    assert "35ml" in packet.selected[0].evidence.exact_text
    assert not any(
        "100ml" in item.evidence.exact_text
        for item in packet.selected
    )
    assert packet.ambiguity_reasons == ()


def test_shared_variant_feature_does_not_resolve_capacity_ambiguity() -> None:
    mention = "香奈儿五号 EDP"
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(143,),
            raw_question=f"{mention} 是多大？",
            question_meaning=f"询问 {mention} 的容量规格",
            safety_sensitive=False,
            product_mention_spans=((0, len(mention)),),
            product_identity_names=(mention,),
        )
    )

    assert any(
        "100ml" in item.evidence.exact_text
        for item in packet.selected
    )
    assert any(
        "35ml" in item.evidence.exact_text
        for item in packet.selected
    )
    assert len(packet.ambiguity_reasons) == 1
    ambiguity = packet.ambiguity_reasons[0]
    assert "多个容量规格变体" in ambiguity
    assert "中文标签所示100ml经典版本为100ml" in ambiguity
    assert "买家照片所示N°5 EDP 35ml喷雾为35ml / 1.2 fl. oz." in ambiguity


def test_multi_product_variant_cues_are_scoped_to_their_product() -> None:
    first = "祖玛珑英国梨与小苍兰买家照片包装"
    second = "香奈儿五号100ml经典版本"
    separator = "和"
    raw_question = f"{first}{separator}{second}分别是什么规格？"
    second_start = len(first) + len(separator)
    packet = ProductEvidenceRetriever(
        _reader(),
        per_product_limit=8,
        total_limit=16,
    ).retrieve(
        _query(
            product_ids=(120, 143),
            raw_question=raw_question,
            question_meaning=(
                f"分别询问{first}与{second}的商品规格"
            ),
            safety_sensitive=False,
            product_mention_spans=(
                (0, len(first)),
                (second_start, second_start + len(second)),
            ),
            product_identity_names=(first, second),
        )
    )

    selected_for_chanel = tuple(
        item.evidence
        for item in packet.selected
        if item.evidence.product_id == 143
    )
    assert selected_for_chanel
    assert any(
        "100ml" in item.exact_text
        for item in selected_for_chanel
    )
    assert not any(
        "35ml" in item.exact_text
        for item in selected_for_chanel
    )
    assert {
        item.variant_scope
        for item in selected_for_chanel
        if item.subject_scope == "exact_variant"
    } == {"中文标签所示100ml经典版本"}
    assert not any(
        "多个容量规格变体" in reason
        for reason in packet.ambiguity_reasons
    )


def test_unrelated_query_does_not_expand_capacity_variants() -> None:
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(143,),
            raw_question="这款闻起来清爽吗？",
            question_meaning="询问香水的清爽气味",
            safety_sensitive=False,
        )
    )

    assert packet.ambiguity_reasons == ()
    assert not any(
        "35ml" in item.evidence.exact_text
        for item in packet.selected
    )


def test_provenance_contrast_cannot_replace_requested_content() -> None:
    product_name = (
        "Elta MD 氨基酸泡沫洁面乳 / 安妍科泡沫洁面乳"
    )
    raw_question = f"{product_name}提亮是商家说的还是有人测过？"
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(67,),
            raw_question=raw_question,
            question_meaning=(
                "询问提亮效果是商家宣称还是有人实际测试过"
            ),
            safety_sensitive=False,
            product_mention_spans=((0, len(product_name)),),
            product_identity_names=(product_name,),
        )
    )

    assert packet.selected[0].evidence.management_label == (
        "consumer_self_report"
    )
    assert "提亮肌肤" in packet.selected[0].evidence.exact_text


def test_free_descriptor_is_supporting_not_dominant_signal() -> None:
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(117,),
            raw_question="茶牛郎适合画什么妆？",
            question_meaning="询问茶牛郎色号适合的妆容",
            safety_sensitive=False,
        )
    )

    assert "清冷小白花妆" in packet.selected[0].evidence.exact_text


def test_confirmed_variant_name_scopes_generic_question() -> None:
    product_name = (
        "URBAN DECAY MOONDUST月耀星眸单色眼影 "
        "坠落银河（昵称：茶牛郎）"
    )
    raw_question = f"{product_name}适合画什么妆？"
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(117,),
            raw_question=raw_question,
            question_meaning="适合用这款眼影画什么类型的妆容",
            safety_sensitive=False,
            product_mention_spans=((0, len(product_name)),),
        )
    )

    assert "清冷小白花妆" in packet.selected[0].evidence.exact_text


def test_partial_free_descriptor_overlap_can_nominate_direct_scene() -> None:
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(57,),
            raw_question="哪个更适合海边？",
            question_meaning="比较防晒的海边场景证据",
            safety_sensitive=False,
        )
    )

    assert "海边游玩" in packet.selected[0].evidence.exact_text


def test_retrieval_never_crosses_product_scope() -> None:
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(34,),
            raw_question="它会不会往下掉？",
            question_meaning="询问膜布是否容易滑落",
            safety_sensitive=False,
        )
    )

    assert all(
        selection.evidence.product_id == 34
        for selection in packet.selected
    )
    assert not any(
        "滑落" in selection.evidence.exact_text
        for selection in packet.selected
    )


def test_safety_query_returns_transcript_with_fail_closed_caveat() -> None:
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(78,),
            raw_question="医美后一定安全吗？",
            question_meaning="询问特殊美容项目后使用是否安全",
            safety_sensitive=True,
        )
    )

    assert packet.selected[0].evidence.management_label == (
        "safety_transcript"
    )
    assert packet.safety_caveats == (
        "这段内容是品牌给出的安全说明，"
        "不能把它当作个人安全保证。",
    )


def test_safety_query_nominates_transcript_across_plain_paraphrase() -> None:
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(78,),
            raw_question="医美后一定安全吗？",
            question_meaning="询问医美后是否安全",
            safety_sensitive=True,
        )
    )

    assert packet.selected
    assert packet.selected[0].evidence.management_label == (
        "safety_transcript"
    )
    assert "特殊美容项目后" in (
        packet.selected[0].evidence.exact_text
    )
    assert packet.safety_caveats == (
        "这段内容是品牌给出的安全说明，"
        "不能把它当作个人安全保证。",
    )


def test_safety_transcript_requires_matching_safety_topic() -> None:
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(78,),
            raw_question="孕期用它一定安全吗？",
            question_meaning="询问孕期使用是否安全",
            safety_sensitive=True,
        )
    )

    assert not any(
        item.evidence.management_label == "safety_transcript"
        for item in packet.selected
    )
    assert packet.safety_caveats == (
        "这款没有足以确认该安全问题的信息，"
        "不能把它当作个人安全保证。",
    )


def test_safety_transcript_rejects_single_character_topic_overlap() -> None:
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(78,),
            raw_question="开封后一定安全吗？",
            question_meaning="询问开封后的使用安全",
            safety_sensitive=True,
        )
    )

    assert not any(
        item.evidence.management_label == "safety_transcript"
        for item in packet.selected
    )
    assert packet.safety_caveats == (
        "这款没有足以确认该安全问题的信息，"
        "不能把它当作个人安全保证。",
    )


def test_safety_query_without_safety_transcript_stays_natural() -> None:
    packet = ProductEvidenceRetriever(_reader()).retrieve(
        _query(
            product_ids=(120,),
            raw_question="孕期用它一定安全吗？",
            question_meaning="询问孕期使用是否安全",
            safety_sensitive=True,
        )
    )

    assert not any(
        item.evidence.management_label == "safety_transcript"
        for item in packet.selected
    )
    assert packet.safety_caveats == (
        "这款没有足以确认该安全问题的信息，"
        "不能把它当作个人安全保证。",
    )


def test_packet_obeys_per_product_and_total_evidence_budgets() -> None:
    packet = ProductEvidenceRetriever(
        _reader(),
        per_product_limit=2,
        total_limit=3,
    ).retrieve(
        _query(
            product_ids=(78, 34),
            raw_question="把这两个的所有信息都讲讲",
            question_meaning="询问两个商品的完整商品信息和使用方式",
            safety_sensitive=False,
        )
    )

    assert len(packet.selected) <= 3
    by_product: dict[int, int] = {}
    for selection in packet.selected:
        product_id = selection.evidence.product_id
        by_product[product_id] = by_product.get(product_id, 0) + 1
    assert all(count <= 2 for count in by_product.values())
