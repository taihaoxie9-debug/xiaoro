(function attachXiaoRoDemoFixture(root) {
    'use strict';

    const products = {
        33: {
            id: 33,
            product_id: 33,
            brand: '雅诗兰黛',
            name: '雅诗兰黛特润修护肌活精华露',
            display_name: '雅诗兰黛特润修护肌活精华露',
            price: 968,
            specification: '50ml',
            category: '精华',
            image_url: '/static/images/products/jd_v3_100022610146.png',
            detail_url: 'https://item.jd.com/100022610146.html'
        },
        39: {
            id: 39,
            product_id: 39,
            brand: '赫莲娜',
            name: '赫莲娜悦颜焕活精华露',
            display_name: '赫莲娜悦颜焕活精华露',
            price: 1080,
            specification: '30ml',
            category: '精华',
            image_url: '/static/images/products/jd_v3_100049220178.png',
            detail_url: 'https://item.jd.com/100049220178.html'
        },
        38: {
            id: 38,
            product_id: 38,
            brand: '理肤泉',
            name: '理肤泉新B5多效修护精华',
            display_name: '理肤泉新B5多效修护精华',
            price: 294,
            specification: '30ml',
            category: '精华',
            image_url: '/static/images/products/jd_v3_100160480140.png',
            detail_url: 'https://item.jd.com/100160480140.html'
        },
        42: {
            id: 42,
            product_id: 42,
            brand: '夸迪',
            name: '稳肌轻龄悬油次抛精华',
            display_name: '夸迪稳肌轻龄悬油次抛精华',
            price: 383.74,
            specification: '30ml',
            category: '精华',
            image_url: '/static/images/products/tmall_v3_998532090974.png',
            detail_url: 'https://detail.tmall.com/item.htm?id=998532090974'
        },
        91: {
            id: 91,
            product_id: 91,
            brand: '玉泽',
            name: '玉泽皮肤屏障修护精华乳',
            display_name: '玉泽皮肤屏障修护精华乳',
            price: 88,
            specification: '50ml',
            category: '精华',
            image_url: '/static/images/products/jd_v3_10069603621835.png',
            detail_url: 'https://item.jd.com/10069603621835.html'
        },
        35: {
            id: 35,
            product_id: 35,
            brand: '修丽可',
            name: '修丽可聚糖多重丰盈精华液',
            display_name: '修丽可聚糖多重丰盈精华液',
            price: 1050,
            specification: '30ml',
            category: '精华',
            image_url: '/static/images/products/jd_v3_100005935030.png',
            detail_url: 'https://item.jd.com/100005935030.html'
        },
        43: {
            id: 43,
            product_id: 43,
            brand: '科颜氏',
            name: '科颜氏高保湿面霜',
            display_name: '科颜氏高保湿面霜',
            price: 315,
            specification: '50ml',
            category: '乳霜',
            image_url: '/static/images/products/jd_v3_100022610088.png',
            detail_url: 'https://item.jd.com/100022610088.html'
        }
    };

    const card = (mode, ids) => ({
        mode,
        visible_product_ids: ids,
        max_cards: ids.length,
        reason: (
            mode === 'none'
                ? null
                : mode === 'single'
                    ? 'product'
                    : mode
        )
    });

    const section = (kind, copyText, extra = {}) => ({
        kind,
        copy_text: copyText,
        used_fact_ids: [],
        used_constraint_ids: [],
        advisor_reason: null,
        advisor_used_fact_ids: [],
        advisor_used_constraint_ids: [],
        slot_id: null,
        product_id: null,
        direct_facts: [],
        ...extra
    });

    const productSection = (
        slot,
        productId,
        copyText,
        facts,
        advisorReason
    ) => section(
        'product',
        copyText,
        {
            slot_id: slot,
            product_id: productId,
            direct_facts: facts.map((fact, index) => ({
                fact_id: `demo:${productId}:direct:${index + 1}`,
                ...fact
            })),
            advisor_reason: advisorReason
        }
    );

    const shelf = () => section('full_cards', null);

    const tags = items => items.map(([product_id, label]) => ({
        product_id,
        label,
        fact_ids: [`demo:${product_id}:${label}`]
    }));
    const comparisonRow = (dimension_id, label, cells) => ({
        dimension_id,
        label,
        cells: cells.map(cell => ({
            ...cell,
            fact_ids: [
                `demo:${cell.product_id}:${dimension_id}`
            ],
            state: 'known'
        }))
    });

    const recommendation = {
        mode: 'recommendation',
        responsibility: 'recommendation',
        recommendation_mode: 'explore',
        copy_source: 'prepared_data',
        sections: [
            section(
                'summary',
                '900 到 1100 这个预算，先看三条不同的精华路线：小棕瓶偏夜间修护和舒缓；绿宝瓶是轻盈凝露的修护抗老路线；紫米精华更侧重保湿、紧致和丰盈感。先按自己更在意的那一项缩小范围。'
            ),
            productSection(
                'p1',
                33,
                '第 7 代小棕瓶把强韧屏障、舒缓泛红和抗老放在主打位置。它是清润琥珀色的液体精华，包装建议早晚用在面霜前。',
                [
                    { label: '参考价 / 规格', display_value: '¥968 / 50ml' },
                    { label: '品牌主打', display_value: '强韧屏障、舒缓泛红与抗老' },
                    { label: '核心成分', display_value: '二裂酵母发酵产物、透明质酸、三肽-32' },
                    { label: '质地', display_value: '清润琥珀色液体，轻薄不粘腻' }
                ],
                '它把夜间修护、舒缓和抗老放在同一条线上，是这一组里很典型的修护向选择。'
            ),
            productSection(
                'p2',
                39,
                '第 6 代绿宝瓶走的是更轻盈的修护抗老路线。海茴香精粹、植物抗老多肽和 EXO SAM 是它的核心叙事，肤感则是轻盈凝露、偏不搓泥。',
                [
                    { label: '参考价 / 规格', display_value: '¥1080 / 30ml' },
                    { label: '品牌主打', display_value: '修护抗老、轻盈凝露质地' },
                    { label: '核心成分', display_value: '海茴香精粹、植物抗老多肽' },
                    { label: '质地', display_value: '轻盈凝露，不搓泥' }
                ],
                '它把修护抗老做得更偏轻盈肤感，和小棕瓶是两种取向。'
            ),
            productSection(
                'p3',
                35,
                '紫米精华更偏保湿打底和紧致丰盈。玻色因、紫米提取物和三重透明质酸是它的核心成分，产品主打保湿润泽、紧致淡纹。',
                [
                    { label: '参考价 / 规格', display_value: '¥1050 / 30ml' },
                    { label: '品牌主打', display_value: '保湿润泽、紧致淡纹' },
                    { label: '核心成分', display_value: '玻色因、紫米提取物、甘草酸二钾与三重透明质酸' }
                ],
                '它提供的是偏紧致和丰盈的路线，不和前两款抢同一个位置。'
            ),
            section(
                'closing',
                '三款分别代表修护舒缓、轻盈凝露和紧致丰盈三条路线，具体选哪一款还要结合你的肤质和当前状态。'
            ),
            shelf()
        ],
        comparison_rows: [],
        winner: {
            status: 'not_applicable',
            winner_product_id: null,
            reason: null,
            fact_ids: [],
            dimension_ids: [],
            tie_reason: null
        },
        visible_product_ids: [33, 39, 35],
        compact_tags: tags([
            [33, '修护'], [33, '舒缓'], [33, '紧致'],
            [39, '轻薄'], [39, '保湿'], [39, '抗皱'],
            [35, '玻色因'], [35, '保湿'], [35, '紧致']
        ]),
        card_display: card('recommendation', [33, 39, 35])
    };

    const productKnowledge = {
        mode: 'product_knowledge',
        responsibility: 'product_knowledge',
        copy_source: 'prepared_data',
        sections: [
            section(
                'summary',
                '第二款是赫莲娜绿宝瓶。它的质地是轻盈凝露，主打轻薄、不搓泥；对于容易觉得精华闷、又想兼顾修护和抗老的人，会更容易接受。'
            ),
            section(
                'answer',
                '海茴香精粹、植物抗老多肽和 EXO SAM 构成了它的修护抗老主线，品牌也把它描述为多肤质可用、偏油皮友好。'
            ),
            shelf()
        ],
        comparison_rows: [],
        winner: { status: 'not_applicable' },
        visible_product_ids: [39],
        compact_tags: tags([[39, '轻薄'], [39, '保湿'], [39, '抗皱']]),
        card_display: card('single', [39])
    };

    const consultation = {
        mode: 'consultation',
        responsibility: 'consultation',
        copy_source: 'prepared_data',
        sections: [
            section(
                'observation',
                '从你描述的“换季泛红”和“T 区出油”来看，更像是偏油的敏感倾向，或者混合偏油、屏障状态不稳定。这个判断还需要结合两颊是否紧绷、刺痛和起皮来确认。要把“换季泛红、T 区出油”记为这次画像吗？'
            ),
            section(
                'summary',
                '确认后，后续推荐和比较会沿用这组肤质观察。'
            )
        ],
        comparison_rows: [],
        winner: { status: 'not_applicable' },
        visible_product_ids: [],
        compact_tags: [],
        card_display: card('none', [])
    };

    const profileConfirmation = {
        mode: 'consultation',
        responsibility: 'consultation',
        copy_source: 'prepared_data',
        sections: [
            section(
                'observation',
                '好，记下了。'
            ),
            section(
                'summary',
                '画像已确认，可以继续比较刚才提到的商品。'
            )
        ],
        comparison_rows: [],
        winner: { status: 'not_applicable' },
        visible_product_ids: [],
        compact_tags: [],
        card_display: card('none', [])
    };

    const comparison = {
        mode: 'comparison',
        responsibility: 'comparison',
        copy_source: 'prepared_data',
        sections: [
            section(
                'summary',
                '按刚才记录的换季泛红和 T 区出油画像，我把第一款和第二款重新放在一起看。'
            ),
            section('comparison', null),
            shelf()
        ],
        requested_comparison_dimensions: ['texture.finish'],
        comparison_rows: [
            comparisonRow(
                'brand_main',
                '主打方向',
                [
                    { product_id: 33, value: '修护、舒缓、紧致' },
                    { product_id: 39, value: '保湿、修护、舒缓、抗皱' }
                ]
            ),
            comparisonRow(
                'texture.finish',
                '质地侧重点',
                [
                    { product_id: 33, value: '清润液体，偏修护护理' },
                    { product_id: 39, value: '凝露、轻薄，偏油皮友好' }
                ]
            ),
            comparisonRow(
                'profile_match',
                '当前画像匹配',
                [
                    { product_id: 33, value: '更优先照顾换季泛红和修护' },
                    { product_id: 39, value: '更优先照顾轻薄和油皮肤感' }
                ]
            )
        ],
        winner: {
            status: 'selected',
            winner_product_id: 33,
            reason: '你现在把换季泛红放在前面，第一款的修护和舒缓方向更贴合；第二款的优势是凝露轻薄、偏油皮友好，适合你把肤感放在第一优先级时选择。',
            fact_ids: ['demo:33:efficacy', 'demo:33:usage'],
            dimension_ids: ['efficacy', 'skin_fit']
        },
        visible_product_ids: [33, 39],
        compact_tags: tags([
            [33, '修护'], [33, '舒缓'], [33, '紧致'],
            [39, '轻薄'], [39, '保湿'], [39, '抗皱']
        ]),
        card_display: card('comparison', [33, 39])
    };

    const imageIdentity = {
        mode: 'image_identity',
        responsibility: 'image_identity',
        copy_source: 'prepared_data',
        sections: [
            section(
                'observation',
                '这张图是理肤泉新 B5 多效修护精华，30ml。它的路线很明确：把修护、补水保湿和舒缓放在一起做，适合拿来应对皮肤状态不稳定、容易泛红的时候。'
            ),
            productSection(
                'p1',
                38,
                null,
                [
                    { label: '参考价 / 规格', display_value: '¥294 / 30ml' },
                    { label: '品牌主打', display_value: '修护、补水保湿、舒缓' },
                    { label: '核心成分', display_value: '维生素原 B5（泛醇）' },
                    { label: '质地', display_value: '清润精华，轻薄好吸收' }
                ],
                null
            ),
            shelf()
        ],
        comparison_rows: [],
        winner: { status: 'not_applicable' },
        visible_product_ids: [38],
        compact_tags: tags([[38, 'B5'], [38, '修护'], [38, '舒缓']]),
        card_display: card('single', [38])
    };

    const imageRecommendation = {
        mode: 'recommendation',
        responsibility: 'recommendation',
        recommendation_mode: 'explore',
        copy_source: 'prepared_data',
        sections: [
            section(
                'summary',
                '图片里的 B5 已经确认，这轮不把它重复算进候选。我按你说的换季泛红和 T 区出油，挑两款同为精华的替代方向。'
            ),
            productSection(
                'p1',
                42,
                '夸迪稳肌轻龄悬油次抛精华走的是悬油、水油双载和微囊的次抛路线，重点是轻盈不黏、吸收快和不搓泥。',
                [
                    { label: '参考价 / 规格', display_value: '¥384 / 30ml' },
                    { label: '品牌主打', display_value: '水油双载、轻盈不黏、紧致舒缓' },
                    { label: '核心成分', display_value: '野大豆油、神经酰胺、维生素E、甘油葡糖苷与海藻糖' },
                    { label: '质地', display_value: '悬油次抛，轻盈不黏' }
                ],
                '在这两款替代精华中，它的轻薄肤感更贴合 T 区出油。'
            ),
            productSection(
                'p2',
                91,
                '玉泽屏障修护精华乳更偏基础保湿、修护和舒缓，质地更接近乳霜型精华。',
                [
                    { label: '参考价 / 规格', display_value: '¥88 / 50ml' },
                    { label: '品牌主打', display_value: '屏障修护、保湿舒缓' },
                    { label: '质地', display_value: '乳霜状质地' }
                ],
                '这一款更偏基础保湿和屏障养护。'
            ),
            section(
                'closing',
                '两款分别偏轻盈肤感和基础屏障养护，可以再按你更在意的方向收窄。'
            ),
            shelf()
        ],
        comparison_rows: [],
        winner: {
            status: 'not_applicable',
            winner_product_id: null,
            reason: null,
            fact_ids: [],
            dimension_ids: [],
            tie_reason: null
        },
        visible_product_ids: [42, 91],
        compact_tags: tags([
            [42, '轻盈'], [42, '不黏'], [42, '次抛'],
            [91, '修护'], [91, '保湿'], [91, '舒缓']
        ]),
        card_display: card('recommendation', [42, 91])
    };

    const imageComparison = {
        mode: 'comparison',
        responsibility: 'comparison',
        copy_source: 'prepared_data',
        sections: [
            section(
                'summary',
                '结合你说的 T 区出油和换季泛红，当前更像偏油的敏感倾向，修护舒缓优先。'
            ),
            section('comparison', null),
            shelf()
        ],
        requested_comparison_dimensions: ['texture.finish'],
        comparison_rows: [
            comparisonRow(
                'brand_main',
                '主打方向',
                [
                    { product_id: 38, value: '修护、补水保湿、舒缓' },
                    { product_id: 42, value: '保湿、抗皱、舒缓' }
                ]
            ),
            comparisonRow(
                'texture.finish',
                '质地侧重点',
                [
                    { product_id: 38, value: '清润精华，按量使用' },
                    { product_id: 42, value: '悬油次抛，轻盈不黏' }
                ]
            ),
            comparisonRow(
                'profile_match',
                '当前画像匹配',
                [
                    { product_id: 38, value: '更贴近泛红与修护' },
                    { product_id: 42, value: '更贴近 T 区出油和轻薄肤感' }
                ]
            )
        ],
        winner: {
            status: 'selected',
            winner_product_id: 38,
            reason: '在当前画像下，B5 的修护和舒缓方向更贴近你描述的换季泛红；夸迪的优势是轻盈不黏，更适合把 T 区出油和肤感放在第一优先级的时候。',
            fact_ids: ['demo:38:efficacy', 'demo:38:ingredient'],
            dimension_ids: ['efficacy', 'skin_fit']
        },
        visible_product_ids: [38, 42],
        compact_tags: tags([
            [38, 'B5'], [38, '修护'], [38, '舒缓'],
            [42, '轻盈'], [42, '不黏'], [42, '次抛']
        ]),
        card_display: card('comparison', [38, 42])
    };

    const demoTelemetry = Object.freeze({
        provider: 'demo',
        model: 'scripted-public-contract',
        prompt_tokens: 0,
        completion_tokens: 0,
        total_tokens: 0,
        latency_ms: 0.0,
        fallback_reason: null
    });
    [
        recommendation,
        productKnowledge,
        consultation,
        profileConfirmation,
        comparison,
        imageIdentity,
        imageRecommendation,
        imageComparison
    ].forEach(contract => {
        contract.copy_source = 'authoritative';
        contract.requested_comparison_dimensions ??= [];
        contract.telemetry = { ...demoTelemetry };
    });

    const state = new Map();

    const textTurns = [
        { intent: 'recommend', presentation: recommendation },
        { intent: 'knowledge', presentation: productKnowledge },
        { intent: 'consultation_answer', presentation: consultation },
        { intent: 'consultation_confirmation', presentation: profileConfirmation },
        { intent: 'comparison', presentation: comparison }
    ];

    const imageTurns = [
        { intent: 'image_identity', presentation: imageIdentity },
        { intent: 'recommend', presentation: imageRecommendation },
        { intent: 'image_compare', presentation: imageComparison }
    ];

    const productList = ids => ids.map(id => products[id]);

    function normalizeMessage(message) {
        return String(message || '')
            .replace(/\s+/g, '')
            .trim();
    }

    function textTurnForMessage(message, cursor) {
        const normalized = normalizeMessage(message);
        if (
            /第一款.*第二款.*(?:哪个|更适合)/.test(normalized)
            || /回到刚才.*推荐/.test(normalized)
        ) {
            return textTurns[4];
        }
        if (/^(确认|好的|设为画像)$/.test(normalized)) {
            return textTurns[3];
        }
        if (
            /换季泛红/.test(normalized)
            && /(?:T区|T区出油|肤质)/.test(normalized)
        ) {
            return textTurns[2];
        }
        if (/第二款.*(?:质地|肤感|适合什么肤质)/.test(normalized)) {
            return textTurns[1];
        }
        if (normalized) {
            return textTurns[0];
        }
        return textTurns[Math.min(cursor, textTurns.length - 1)];
    }

    function imageTurnForMessage(message, images, cursor) {
        if (images?.length) {
            return imageTurns[0];
        }
        const normalized = normalizeMessage(message);
        if (/(?:哪个|更适合|对比|修丽可)/.test(normalized)) {
            return imageTurns[2];
        }
        if (normalized) {
            return imageTurns[1];
        }
        return imageTurns[Math.min(cursor, imageTurns.length - 1)];
    }

    function eventsForTurn(turn, version) {
        const presentation = turn.presentation;
        const ids = presentation.visible_product_ids;
        const events = [
            ['start', { status: 'started' }],
            ['stage', { stage: turn.intent, message: '正在理解你的问题' }],
            ['intent', { intent: turn.intent, guide: true }],
            ['stage', { stage: 'retrieval', message: '正在查看相关商品资料' }]
        ];
        if (ids.length) {
            events.push(
                ['answer_contract', {
                    answer_contract: {
                        product_count: ids.length,
                        winner_status: presentation.winner.status === 'selected'
                            ? 'SELECTED'
                            : 'NOT_APPLICABLE',
                        has_unknown_skin: false
                    },
                    product_count: ids.length,
                    winner_status: presentation.winner.status === 'selected'
                        ? 'SELECTED'
                        : 'NOT_APPLICABLE',
                    has_unknown_skin: false
                }],
                ['card_display_contract', presentation.card_display],
                ['products', { products: productList(ids) }]
            );
        } else {
            events.push(
                ['answer_contract', {
                    answer_contract: {
                        product_count: 0,
                        winner_status: 'NOT_APPLICABLE',
                        has_unknown_skin: false
                    },
                    product_count: 0,
                    winner_status: 'NOT_APPLICABLE',
                    has_unknown_skin: false
                }],
                ['card_display_contract', presentation.card_display],
                ['products', { products: [] }]
            );
        }
        events.push(
            ['stage', { stage: 'decision', message: '正在整理适合你的回答' }],
            ['presentation_contract', presentation]
        );
        if (ids.length) {
            events.push(
                ['feedback_target', {
                    conversation_version: version,
                    displayed_product_ids: ids,
                    profile_version: 1
                }]
            );
        }
        events.push(['end', { conversation_version: version }]);
        return events;
    }

    function streamResponse(events) {
        const encoder = new TextEncoder();
        let index = 0;
        const stream = new ReadableStream({
            start(controller) {
                const pump = () => {
                    if (index >= events.length) {
                        controller.close();
                        return;
                    }
                    const [name, data] = events[index++];
                    controller.enqueue(encoder.encode(
                        `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`
                    ));
                    window.setTimeout(pump, name === 'stage' ? 520 : 90);
                };
                pump();
            }
        });
        return new Response(stream, {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' }
        });
    }

    root.XiaoRoDemoFixture = Object.freeze({
        createResponse({ sessionId, images, message }) {
            const existing = state.get(sessionId) || {
                mode: images?.length ? 'image' : 'text',
                cursors: {
                    text: 0,
                    image: 0
                },
                version: 0
            };
            if (images?.length) existing.mode = 'image';
            const mode = existing.mode;
            const cursor = existing.cursors[mode] || 0;
            const turn = mode === 'image'
                ? imageTurnForMessage(message, images, cursor)
                : textTurnForMessage(message, cursor);
            existing.cursors[mode] = cursor + 1;
            existing.version += 1;
            state.set(sessionId, existing);
            return streamResponse(
                eventsForTurn(turn, existing.version)
            );
        }
    });
})(window);
