(function attachXiaoRoPresentation(root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) {
        module.exports = api;
    }
    if (root) {
        root.XiaoRoPresentation = api;
    }
})(
    typeof window !== 'undefined' ? window : globalThis,
    function createXiaoRoPresentation() {
        'use strict';

        const HISTORY_VERSION = 1;
        const PRODUCT_MODES = new Set([
            'recommendation',
            'comparison',
            'single_product',
            'product_knowledge',
            'image_identity'
        ]);
        const THINKING_STAGES = Object.freeze({
            recommend: ['understanding', 'retrieval', 'decision', 'copy'],
            comparison: ['understanding', 'retrieval', 'decision', 'copy'],
            suitability: ['understanding', 'retrieval', 'decision', 'copy'],
            knowledge: ['understanding', 'retrieval', 'copy'],
            followup: ['state', 'decision', 'copy'],
            revise: ['state', 'retrieval', 'decision', 'copy'],
            image_identity: ['image_observation', 'decision', 'copy'],
            image_recommend: [
                'image_observation',
                'retrieval',
                'decision',
                'copy'
            ],
            image_suitability: [
                'image_observation',
                'decision',
                'copy'
            ],
            image_compare: [
                'image_observation',
                'decision',
                'copy'
            ],
            consultation_entry: ['state', 'observation', 'copy'],
            consultation_answer: ['state', 'observation', 'copy'],
            consultation_clarification: ['state', 'observation', 'copy'],
            consultation_provisional: ['state', 'observation', 'copy'],
            consultation_confirmation: ['state', 'observation', 'copy'],
            consultation_rejection: ['state', 'observation', 'copy'],
            consultation_medical_escalation: [
                'state',
                'observation'
            ],
            clarify: [],
            error: []
        });
        const STAGE_LABELS = Object.freeze({
            understanding: '正在理解这次需求',
            state: '正在读取本轮上下文',
            image_observation: '正在核对图片商品',
            retrieval: '正在查找可用证据',
            observation: '正在整理当前观察',
            decision: '正在核对选择条件',
            copy: '正在整理导购建议'
        });
        function clone(value) {
            if (value === undefined) return undefined;
            return JSON.parse(JSON.stringify(value));
        }

        function sameIds(left, right) {
            return (
                Array.isArray(left)
                && Array.isArray(right)
                && left.length === right.length
                && left.every((item, index) => (
                    Number.isInteger(item)
                    && item > 0
                    && item === right[index]
                ))
                && new Set(left).size === left.length
            );
        }

        function validateCardDisplay(contract) {
            if (!contract || typeof contract !== 'object') {
                throw new Error('PRESENTATION_CARD_CONTRACT_INVALID');
            }
            const ids = contract.visible_product_ids;
            if (
                !Array.isArray(ids)
                || ids.some(id => !Number.isInteger(id) || id <= 0)
                || new Set(ids).size !== ids.length
                || !Number.isInteger(contract.max_cards)
                || contract.max_cards !== ids.length
            ) {
                throw new Error('PRESENTATION_CARD_CONTRACT_INVALID');
            }
            const validMode = (
                (contract.mode === 'none' && ids.length === 0)
                || (contract.mode === 'single' && ids.length === 1)
                || (
                    contract.mode === 'recommendation'
                    && ids.length >= 1
                    && ids.length <= 4
                )
                || (
                    contract.mode === 'comparison'
                    && ids.length >= 2
                    && ids.length <= 4
                )
            );
            if (!validMode) {
                throw new Error('PRESENTATION_CARD_CONTRACT_INVALID');
            }
            return clone(contract);
        }

        function validateProducts(products) {
            if (!Array.isArray(products)) {
                throw new Error('PRESENTATION_PRODUCTS_INVALID');
            }
            const ids = products.map(product => Number(
                product?.id ?? product?.product_id
            ));
            if (
                ids.some(id => !Number.isInteger(id) || id <= 0)
                || new Set(ids).size !== ids.length
            ) {
                throw new Error('PRESENTATION_PRODUCTS_INVALID');
            }
            return products.map((product, index) => ({
                ...clone(product),
                id: ids[index],
                product_id: ids[index]
            }));
        }

        function validateWinner(
            winner,
            mode,
            visibleProductIds,
            recommendationMode = null
        ) {
            if (!winner || typeof winner !== 'object') {
                if (![
                    'recommendation',
                    'comparison'
                ].includes(mode)) {
                    return { status: 'not_applicable' };
                }
                throw new Error('PRESENTATION_WINNER_INVALID');
            }
            const status = winner.status;
            if (mode === 'recommendation') {
                if (
                    recommendationMode === 'explore'
                    && status !== 'not_applicable'
                ) {
                    throw new Error('PRESENTATION_WINNER_INVALID');
                }
                if (recommendationMode === 'explore') {
                    if (
                        winner.winner_product_id !== null
                        && winner.winner_product_id !== undefined
                        || winner.reason !== null
                        && winner.reason !== undefined
                        || winner.tie_reason !== null
                        && winner.tie_reason !== undefined
                        || !Array.isArray(winner.fact_ids)
                        || winner.fact_ids.length
                        || !Array.isArray(winner.dimension_ids)
                        || winner.dimension_ids.length
                    ) {
                        throw new Error(
                            'PRESENTATION_WINNER_INVALID'
                        );
                    }
                    return clone(winner);
                }
                if (
                    recommendationMode !== 'fit'
                    || status !== 'selected'
                    || !Number.isInteger(winner.winner_product_id)
                    || winner.winner_product_id !== visibleProductIds[0]
                    || typeof winner.reason !== 'string'
                    || !winner.reason.trim()
                    || !Array.isArray(winner.fact_ids)
                    || winner.fact_ids.length === 0
                ) {
                    throw new Error('PRESENTATION_WINNER_INVALID');
                }
                return clone(winner);
            }
            if (mode !== 'comparison') {
                if (status !== 'not_applicable') {
                    throw new Error('PRESENTATION_WINNER_INVALID');
                }
                return clone(winner);
            }
            if (![
                'selected',
                'tied',
                'insufficient'
            ].includes(status)) {
                throw new Error('PRESENTATION_WINNER_INVALID');
            }
            if (status === 'selected') {
                if (
                    !Number.isInteger(winner.winner_product_id)
                    || !visibleProductIds.includes(
                        winner.winner_product_id
                    )
                    || typeof winner.reason !== 'string'
                    || !winner.reason.trim()
                    || !Array.isArray(winner.fact_ids)
                    || winner.fact_ids.length === 0
                ) {
                    throw new Error('PRESENTATION_WINNER_INVALID');
                }
            } else if (
                winner.winner_product_id !== null
                && winner.winner_product_id !== undefined
            ) {
                throw new Error('PRESENTATION_WINNER_INVALID');
            }
            if (
                status === 'tied'
                && (
                    typeof winner.tie_reason !== 'string'
                    || !winner.tie_reason.trim()
                )
            ) {
                throw new Error('PRESENTATION_WINNER_INVALID');
            }
            return clone(winner);
        }

        function validatePresentation(presentation, cardDisplay) {
            if (
                !presentation
                || typeof presentation !== 'object'
                || !Array.isArray(presentation.sections)
                || typeof presentation.mode !== 'string'
            ) {
                throw new Error('PRESENTATION_CONTRACT_INVALID');
            }
            const embedded = validateCardDisplay(
                presentation.card_display
            );
            if (
                !cardDisplay
                || embedded.mode !== cardDisplay.mode
                || embedded.max_cards !== cardDisplay.max_cards
                || !sameIds(
                    embedded.visible_product_ids,
                    cardDisplay.visible_product_ids
                )
            ) {
                throw new Error(
                    'PRESENTATION_CARD_CONTRACT_MISMATCH'
                );
            }
            const productSections = presentation.sections.filter(
                section => section?.kind === 'product'
            );
            const productIds = productSections.map(
                section => Number(section.product_id)
            );
            const allowsProductSections = [
                'recommendation',
                'image_identity'
            ].includes(presentation.mode);
            if (
                allowsProductSections
                && !sameIds(
                    productIds,
                    cardDisplay.visible_product_ids
                )
            ) {
                throw new Error(
                    'PRESENTATION_CARD_CONTRACT_MISMATCH'
                );
            }
            if (
                !allowsProductSections
                && productSections.length
            ) {
                throw new Error(
                    'PRESENTATION_CARD_CONTRACT_MISMATCH'
                );
            }
            if (
                !PRODUCT_MODES.has(presentation.mode)
                && cardDisplay.visible_product_ids.length
            ) {
                throw new Error('PRESENTATION_CONTRACT_INVALID');
            }
            productSections.forEach((section, index) => {
                if (section.slot_id !== `p${index + 1}`) {
                    throw new Error(
                        'PRESENTATION_SLOT_ORDER_MISMATCH'
                    );
                }
            });
            const comparisonRows = Array.isArray(
                presentation.comparison_rows
            )
                ? presentation.comparison_rows
                : [];
            const recommendationMode = presentation.recommendation_mode;
            if (
                presentation.mode === 'recommendation'
                && !['explore', 'fit'].includes(recommendationMode)
            ) {
                throw new Error(
                    'PRESENTATION_RECOMMENDATION_MODE_INVALID'
                );
            }
            if (
                presentation.mode !== 'recommendation'
                && recommendationMode !== null
                && recommendationMode !== undefined
            ) {
                throw new Error('PRESENTATION_CONTRACT_INVALID');
            }
            if (
                recommendationMode === 'fit'
                && cardDisplay.visible_product_ids.length !== 1
            ) {
                throw new Error(
                    'PRESENTATION_CARD_CONTRACT_MISMATCH'
                );
            }
            const winner = validateWinner(
                presentation.winner,
                presentation.mode,
                cardDisplay.visible_product_ids,
                recommendationMode
            );
            if (presentation.mode === 'recommendation') {
                const closingSections = presentation.sections.filter(
                    section => section?.kind === 'closing'
                );
                if (closingSections.length !== 1) {
                    throw new Error('PRESENTATION_CONTRACT_INVALID');
                }
                const closingCopy = closingSections[0].copy_text;
                if (
                    recommendationMode === 'fit'
                    && closingCopy !== null
                    && closingCopy !== undefined
                ) {
                    throw new Error('PRESENTATION_CONTRACT_INVALID');
                }
                if (
                    recommendationMode === 'explore'
                    && (
                        typeof closingCopy !== 'string'
                        || !closingCopy.trim()
                    )
                ) {
                    throw new Error('PRESENTATION_CONTRACT_INVALID');
                }
            }
            if (presentation.mode === 'comparison') {
                if (!comparisonRows.length) {
                    throw new Error('PRESENTATION_CONTRACT_INVALID');
                }
                comparisonRows.forEach(row => {
                    const cellIds = Array.isArray(row?.cells)
                        ? row.cells.map(cell => Number(cell?.product_id))
                        : [];
                    if (
                        typeof row?.label !== 'string'
                        || !row.label.trim()
                        || !sameIds(
                            cellIds,
                            cardDisplay.visible_product_ids
                        )
                    ) {
                        throw new Error(
                            'PRESENTATION_CARD_CONTRACT_MISMATCH'
                        );
                    }
                });
            } else if (comparisonRows.length) {
                throw new Error('PRESENTATION_CONTRACT_INVALID');
            }
            return clone(presentation);
        }

        function createTurnState() {
            return {
                intent: null,
                thinkingStages: [],
                cardDisplay: null,
                products: [],
                presentation: null,
                message: '',
                pitfalls: [],
                evidence: {},
                ended: false
            };
        }

        function reduceGuideEvent(previous, event) {
            const state = {
                ...createTurnState(),
                ...clone(previous || {})
            };
            if (
                !event
                || typeof event !== 'object'
                || typeof event.event !== 'string'
            ) {
                throw new Error('PRESENTATION_EVENT_INVALID');
            }
            const data = event.data || {};
            switch (event.event) {
                case 'stage':
                    state.thinkingStages = [
                        ...state.thinkingStages,
                        {
                            stage: String(
                                data.stage || data.status || ''
                            ),
                            message: String(
                                data.message || data.summary || ''
                            )
                        }
                    ].slice(-4);
                    break;
                case 'intent':
                    state.intent = String(
                        data.intent || data.mode || ''
                    ) || null;
                    break;
                case 'card_display_contract':
                    state.cardDisplay = validateCardDisplay(data);
                    if (state.cardDisplay.mode === 'none') {
                        state.products = [];
                        state.presentation = null;
                    }
                    break;
                case 'products':
                    state.products = validateProducts(
                        data.products || data.cards || []
                    );
                    break;
                case 'presentation_contract':
                    if (!state.cardDisplay) {
                        state.cardDisplay = validateCardDisplay(
                            data.card_display
                        );
                    }
                    state.presentation = validatePresentation(
                        data,
                        state.cardDisplay
                    );
                    break;
                case 'pitfalls':
                    state.pitfalls = clone(data.pitfalls || []);
                    break;
                case 'scenario_evidence':
                case 'merchant_claims':
                case 'review_evidence':
                case 'product_evidence':
                case 'general_knowledge':
                case 'citations':
                    state.evidence = {
                        ...state.evidence,
                        [event.event]: clone(data)
                    };
                    break;
                case 'message':
                    state.message += String(data.content || '');
                    break;
                case 'end':
                    state.ended = true;
                    break;
                default:
                    break;
            }
            return state;
        }

        function resolveVisibleProducts(state) {
            const contract = state?.cardDisplay;
            if (!contract || contract.mode === 'none') return [];
            const byId = new Map(
                validateProducts(state.products || []).map(
                    product => [product.id, product]
                )
            );
            const selected = contract.visible_product_ids.map(
                id => byId.get(id)
            );
            if (selected.some(product => !product)) {
                throw new Error('PRESENTATION_PRODUCT_MISSING');
            }
            return selected;
        }

        function publicProductName(product, fallback = '推荐商品') {
            const displayName = String(
                product?.display_name || product?.name || ''
            ).trim();
            return displayName || fallback;
        }

        function substituteProductSlots(text, slots) {
            const source = String(text || '');
            const slotMap = new Map(
                (Array.isArray(slots) ? slots : []).map(
                    slot => [slot.slot_id, slot]
                )
            );
            const tokens = [];
            const pushText = value => {
                if (!value) return;
                const previous = tokens[tokens.length - 1];
                if (previous?.type === 'text') {
                    previous.value += value;
                } else {
                    tokens.push({ type: 'text', value });
                }
            };
            let cursor = 0;
            const pattern = /\{\{product:(p[1-4])\}\}/g;
            let match;
            while ((match = pattern.exec(source)) !== null) {
                if (match.index > cursor) {
                    pushText(source.slice(cursor, match.index));
                }
                const slot = slotMap.get(match[1]);
                if (slot) {
                    tokens.push({
                        type: 'product_ref',
                        slot_id: match[1],
                        product_id: slot.product_id
                    });
                } else {
                    pushText(match[0]);
                }
                cursor = pattern.lastIndex;
            }
            if (cursor < source.length) {
                pushText(source.slice(cursor));
            }
            return tokens;
        }

        function serializePresentation(state) {
            return {
                version: HISTORY_VERSION,
                intent: state?.intent || null,
                cardDisplay: clone(state?.cardDisplay || null),
                products: clone(state?.products || []),
                presentation: clone(state?.presentation || null),
                message: String(state?.message || ''),
                pitfalls: clone(state?.pitfalls || []),
                evidence: clone(state?.evidence || {}),
                ended: Boolean(state?.ended)
            };
        }

        function restorePresentation(serialized) {
            if (
                !serialized
                || typeof serialized !== 'object'
                || serialized.version !== HISTORY_VERSION
            ) {
                throw new Error('PRESENTATION_HISTORY_INVALID');
            }
            const state = createTurnState();
            state.intent = serialized.intent || null;
            state.message = String(serialized.message || '');
            state.pitfalls = clone(serialized.pitfalls || []);
            state.evidence = clone(serialized.evidence || {});
            state.ended = Boolean(serialized.ended);
            state.thinkingStages = [];
            if (serialized.cardDisplay) {
                state.cardDisplay = validateCardDisplay(
                    serialized.cardDisplay
                );
            }
            state.products = validateProducts(
                serialized.products || []
            );
            if (serialized.presentation) {
                state.presentation = validatePresentation(
                    serialized.presentation,
                    state.cardDisplay
                );
            }
            return state;
        }

        function buildPresentationView(state, allowedModes) {
            if (!state?.presentation || !state?.cardDisplay) {
                throw new Error('PRESENTATION_VIEW_INCOMPLETE');
            }
            if (
                allowedModes
                && !allowedModes.includes(state.presentation.mode)
            ) {
                throw new Error('PRESENTATION_MODE_MISMATCH');
            }
            const presentation = validatePresentation(
                state.presentation,
                state.cardDisplay
            );
            const products = resolveVisibleProducts(state);
            const productSections = presentation.sections.filter(
                section => section.kind === 'product'
            );
            const slots = productSections.map(section => ({
                slot_id: section.slot_id,
                product_id: section.product_id
            }));
            const refs = [];
            const seenRefs = new Set();
            presentation.sections.forEach(section => {
                substituteProductSlots(section.copy_text || '', slots)
                    .filter(token => token.type === 'product_ref')
                    .forEach(token => {
                        const key = `${token.slot_id}:${token.product_id}`;
                        if (seenRefs.has(key)) return;
                        seenRefs.add(key);
                        refs.push({
                            slot_id: token.slot_id,
                            product_id: token.product_id
                        });
                    });
            });
            return {
                mode: presentation.mode,
                recommendationMode: (
                    presentation.recommendation_mode || null
                ),
                copySource: presentation.copy_source,
                sections: clone(presentation.sections),
                products,
                inlineCardIds: productSections.map(
                    section => section.product_id
                ),
                fullCardIds: [
                    ...presentation.card_display.visible_product_ids
                ],
                productRefs: refs,
                comparisonRows: clone(
                    presentation.comparison_rows || []
                ),
                winner: clone(presentation.winner),
                compactTags: clone(presentation.compact_tags || [])
            };
        }

        function renderRecommendationPresentation(state) {
            return buildPresentationView(state, ['recommendation']);
        }

        function renderComparisonPresentation(state) {
            return buildPresentationView(state, ['comparison']);
        }

        function renderSingleProductPresentation(state) {
            return buildPresentationView(state, ['single_product']);
        }

        function renderProductKnowledgePresentation(state) {
            return buildPresentationView(state, ['product_knowledge']);
        }

        function renderGeneralKnowledgePresentation(state) {
            return buildPresentationView(state, ['general_knowledge']);
        }

        function renderFollowupPresentation(state) {
            return buildPresentationView(
                state,
                ['recommendation']
            );
        }

        function renderImagePresentation(state) {
            return buildPresentationView(
                state,
                ['image_identity']
            );
        }

        function renderConsultationPresentation(state) {
            return buildPresentationView(state, ['consultation']);
        }

        function renderClarificationPresentation(state) {
            return buildPresentationView(state, ['clarification']);
        }

        function renderErrorPresentation(state) {
            return buildPresentationView(state, ['error']);
        }

        function presentationViewForState(state) {
            const mode = state?.presentation?.mode;
            if (mode === 'recommendation') {
                return renderRecommendationPresentation(state);
            }
            if (mode === 'comparison') {
                return renderComparisonPresentation(state);
            }
            if (mode === 'single_product') {
                return renderSingleProductPresentation(state);
            }
            if (mode === 'product_knowledge') {
                return renderProductKnowledgePresentation(state);
            }
            if (mode === 'general_knowledge') {
                return renderGeneralKnowledgePresentation(state);
            }
            if (mode === 'image_identity') {
                return renderImagePresentation(state);
            }
            if (mode === 'consultation') {
                return renderConsultationPresentation(state);
            }
            if (mode === 'clarification') {
                return renderClarificationPresentation(state);
            }
            if (mode === 'error') {
                return renderErrorPresentation(state);
            }
            throw new Error('PRESENTATION_MODE_UNSUPPORTED');
        }

        function appendCopyTokens(parent, text, slots, productsById) {
            substituteProductSlots(text, slots).forEach(token => {
                if (token.type === 'text') {
                    parent.appendChild(
                        parent.ownerDocument.createTextNode(token.value)
                    );
                    return;
                }
                const product = productsById.get(token.product_id);
                if (!product) {
                    throw new Error('PRESENTATION_PRODUCT_MISSING');
                }
                const button = parent.ownerDocument.createElement(
                    'button'
                );
                button.type = 'button';
                button.className = 'guide-product-ref';
                button.dataset.guideProductRef = String(
                    token.product_id
                );
                button.textContent = publicProductName(
                    product,
                    `商品 ${token.product_id}`
                );
                parent.appendChild(button);
            });
        }

        function createInlineProductCard(
            documentRef,
            product,
            helpers
        ) {
            const figure = documentRef.createElement('figure');
            figure.className = 'inline-product-image';
            figure.dataset.guideCardForm = 'inline';
            figure.dataset.guideProductId = String(product.id);

            const content = documentRef.createElement('div');
            content.className = 'guide-inline-product-content';
            const visual = documentRef.createElement('div');
            visual.className = 'guide-inline-product-visual';
            const image = documentRef.createElement('img');
            const imageUrl = helpers.getImageUrl
                ? helpers.getImageUrl(product)
                : String(product.image_url || '');
            if (imageUrl) image.src = imageUrl;
            image.alt = publicProductName(product);
            image.width = 112;
            image.height = 114;
            image.loading = 'lazy';
            image.decoding = 'async';
            visual.appendChild(image);

            const info = documentRef.createElement('div');
            info.className = 'guide-inline-product-info';
            if (product.brand) {
                const brand = documentRef.createElement('span');
                brand.className = 'guide-inline-product-brand';
                brand.textContent = product.brand;
                info.appendChild(brand);
            }
            const name = documentRef.createElement('strong');
            name.className = 'guide-inline-product-name';
            name.textContent = publicProductName(product);
            const rule = documentRef.createElement('span');
            rule.className = 'guide-inline-product-rule';
            const price = documentRef.createElement('span');
            price.className = 'guide-inline-product-price';
            price.textContent = helpers.formatPrice
                ? helpers.formatPrice(product)
                : String(product.price ?? '价格待确认');
            info.append(name, rule, price);
            content.append(visual, info);

            const detailUrl = helpers.getDetailUrl
                ? helpers.getDetailUrl(product)
                : '';
            if (detailUrl) {
                const link = documentRef.createElement('a');
                link.href = detailUrl;
                link.target = '_blank';
                link.rel = 'noopener';
                link.dataset.detailUrl = detailUrl;
                link.appendChild(content);
                figure.appendChild(link);
            } else {
                figure.appendChild(content);
            }
            return figure;
        }

        function createShelfProductCard(
            documentRef,
            product,
            compactTags,
            helpers
        ) {
            const card = documentRef.createElement('article');
            card.className = (
                'recommendation-card guide-product-shelf-card'
            );
            card.dataset.guideCardForm = 'shelf';
            card.dataset.guideProductId = String(product.id);

            const detailUrl = helpers.getDetailUrl
                ? helpers.getDetailUrl(product)
                : '';
            if (detailUrl) {
                card.dataset.detailUrl = detailUrl;
                card.setAttribute('role', 'link');
                card.setAttribute('tabindex', '0');
            }

            const favorite = documentRef.createElement('button');
            favorite.type = 'button';
            favorite.className = 'recommendation-save';
            favorite.dataset.favoriteProductId = String(product.id);
            const isFavorite = Boolean(
                helpers.isFavorite?.(product)
            );
            if (isFavorite) {
                favorite.className += ' active';
            }
            const favoriteAction = isFavorite ? '取消收藏' : '收藏';
            favorite.setAttribute(
                'aria-label',
                `${favoriteAction} ${publicProductName(product)}`
            );
            favorite.setAttribute('title', favoriteAction);
            const favoriteIcon = documentRef.createElement('i');
            favoriteIcon.setAttribute(
                'data-feather',
                isFavorite ? 'heart' : 'bookmark'
            );
            favorite.appendChild(favoriteIcon);

            const image = documentRef.createElement('img');
            image.className = 'recommendation-image';
            image.src = helpers.getImageUrl
                ? helpers.getImageUrl(product)
                : String(product.image_url || '');
            image.alt = publicProductName(product);
            image.width = 180;
            image.height = 118;
            image.loading = 'lazy';
            image.decoding = 'async';

            const body = documentRef.createElement('div');
            body.className = 'recommendation-body';
            const name = documentRef.createElement('div');
            name.className = 'recommendation-name';
            name.textContent = publicProductName(product);
            const price = documentRef.createElement('div');
            price.className = 'recommendation-price';
            price.textContent = helpers.formatPrice
                ? helpers.formatPrice(product)
                : String(product.price ?? '价格待确认');
            body.append(name, price);

            if (compactTags.length) {
                const tags = documentRef.createElement('div');
                tags.className = 'recommendation-meta';
                compactTags.forEach(tag => {
                    const chip = documentRef.createElement('span');
                    chip.className = (
                        'recommendation-chip recommendation-contract-tag'
                    );
                    chip.textContent = tag.label;
                    tags.appendChild(chip);
                });
                body.appendChild(tags);
            }

            if (detailUrl) {
                const link = documentRef.createElement('a');
                link.className = (
                    'recommendation-link guide-product-detail-link'
                );
                link.href = detailUrl;
                link.target = '_blank';
                link.rel = 'noopener';
                link.dataset.detailUrl = detailUrl;
                link.textContent = '去商品页查实时价';
                body.appendChild(link);
            }

            card.append(favorite, image, body);
            return card;
        }

        function createProductShelf(
            documentRef,
            view,
            productsById,
            helpers
        ) {
            if (!view.fullCardIds.length) {
                return null;
            }
            const section = documentRef.createElement('section');
            section.className = (
                'guide-presentation-section guide-presentation-full-cards'
            );
            section.dataset.sectionKind = 'full_cards';
            const title = documentRef.createElement('h3');
            title.textContent = '本轮提到的商品';
            const grid = documentRef.createElement('div');
            grid.className = 'recommendation-grid';
            const tagsByProductId = new Map();
            view.compactTags.forEach(tag => {
                const productId = Number(tag?.product_id);
                if (
                    !Number.isInteger(productId)
                    || !productsById.has(productId)
                    || typeof tag?.label !== 'string'
                    || !tag.label
                ) {
                    return;
                }
                const tags = tagsByProductId.get(productId) || [];
                if (tags.length < 3) {
                    tags.push({ label: tag.label });
                }
                tagsByProductId.set(productId, tags);
            });
            view.fullCardIds.forEach(productId => {
                const product = productsById.get(productId);
                if (!product) {
                    throw new Error('PRESENTATION_PRODUCT_MISSING');
                }
                grid.appendChild(
                    createShelfProductCard(
                        documentRef,
                        product,
                        tagsByProductId.get(productId) || [],
                        helpers
                    )
                );
            });
            section.append(title, grid);
            return section;
        }

        function createDirectFacts(documentRef, directFacts) {
            const facts = documentRef.createElement('dl');
            (Array.isArray(directFacts) ? directFacts : []).forEach(
                fact => {
                    if (!fact?.display_value) return;
                    const row = documentRef.createElement('div');
                    row.className = 'guide-direct-fact';
                    const label = documentRef.createElement('dt');
                    label.textContent = fact.label || '已核对';
                    const value = documentRef.createElement('dd');
                    value.textContent = fact.display_value;
                    row.append(label, value);
                    facts.appendChild(row);
                }
            );
            return facts;
        }

        function createComparisonTable(
            documentRef,
            comparisonRows,
            visibleProductIds,
            productsById
        ) {
            if (
                !Array.isArray(comparisonRows)
                || !Array.isArray(visibleProductIds)
                || comparisonRows.length === 0
            ) {
                return null;
            }

            const wrapper = documentRef.createElement('div');
            wrapper.className = 'guide-comparison-scroll';
            wrapper.dataset.guideComparisonTable = 'true';
            const table = documentRef.createElement('table');
            table.className = 'compare-table guide-comparison-table';
            table.setAttribute('aria-label', '商品横向对比');

            const head = documentRef.createElement('thead');
            const headRow = documentRef.createElement('tr');
            const dimensionHeading = documentRef.createElement('th');
            dimensionHeading.setAttribute('scope', 'col');
            dimensionHeading.textContent = '对比项';
            headRow.appendChild(dimensionHeading);
            visibleProductIds.forEach((productId, index) => {
                const product = productsById.get(productId);
                if (!product) {
                    throw new Error('PRESENTATION_PRODUCT_MISSING');
                }
                const heading = documentRef.createElement('th');
                heading.setAttribute('scope', 'col');
                heading.textContent = publicProductName(
                    product,
                    `商品 ${index + 1}`
                );
                headRow.appendChild(heading);
            });
            head.appendChild(headRow);

            const body = documentRef.createElement('tbody');
            comparisonRows.forEach(row => {
                const tableRow = documentRef.createElement('tr');
                const label = documentRef.createElement('th');
                label.setAttribute('scope', 'row');
                label.textContent = row.label;
                tableRow.appendChild(label);
                const cellsByProductId = new Map(
                    row.cells.map(cell => [
                        Number(cell.product_id),
                        cell
                    ])
                );
                visibleProductIds.forEach(productId => {
                    const contractCell = cellsByProductId.get(productId);
                    if (!contractCell) {
                        throw new Error(
                            'PRESENTATION_CARD_CONTRACT_MISMATCH'
                        );
                    }
                    const cell = documentRef.createElement('td');
                    cell.textContent = contractCell.value;
                    tableRow.appendChild(cell);
                });
                body.appendChild(tableRow);
            });
            table.append(head, body);
            wrapper.appendChild(table);
            return wrapper;
        }

        function createWinnerConclusion(
            documentRef,
            winner,
            productsById,
            labelText = '综合判断：'
        ) {
            if (!winner || winner.status === 'not_applicable') {
                return null;
            }
            const block = documentRef.createElement('div');
            block.className = 'guide-winner-conclusion';
            block.dataset.guideWinnerStatus = winner.status;
            const text = documentRef.createElement('span');
            if (winner.status === 'selected') {
                const product = productsById.get(
                    Number(winner.winner_product_id)
                );
                if (!product) {
                    throw new Error('PRESENTATION_PRODUCT_MISSING');
                }
                text.textContent = (
                    `${publicProductName(product, '当前胜出商品')}。`
                    + `${winner.reason}`
                );
            } else if (winner.status === 'tied') {
                text.textContent = (
                    `暂不指定唯一首选。${winner.tie_reason}`
                );
            } else {
                text.textContent = '现有事实不足以指定唯一首选。';
            }
            if (labelText) {
                const label = documentRef.createElement('strong');
                label.textContent = labelText;
                block.append(label, text);
            } else {
                block.appendChild(text);
            }
            return block;
        }

        function compactEvidenceText(value, limit = 96) {
            const text = String(value || '').replace(/\s+/g, ' ').trim();
            if (!text) return '';
            return text.length > limit
                ? `${text.slice(0, limit - 1).trim()}…`
                : text;
        }

        function numericProductId(value) {
            const id = Number(value);
            return Number.isInteger(id) && id > 0 ? id : null;
        }

        function evidencePrefix(productId, productsById) {
            const id = numericProductId(productId);
            if (id === null) return '';
            const product = productsById.get(id);
            return product?.name ? `${product.name}：` : `商品 ${id}：`;
        }

        function pushEvidenceRow(
            groups,
            key,
            title,
            value,
            productId,
            productsById,
            metadata = {}
        ) {
            const text = compactEvidenceText(value);
            if (!text) return;
            let group = groups.find(item => item.key === key);
            if (!group) {
                group = { key, title, items: [] };
                groups.push(group);
            }
            const prefix = evidencePrefix(productId, productsById);
            const line = `${prefix}${text}`;
            if (!group.items.some(item => item.text === line)) {
                group.items.push({
                    text: line,
                    evidenceId: metadata.evidenceId || null,
                    productId: numericProductId(
                        metadata.productId
                    )
                });
            }
        }

        function evidenceGroupsForState(
            evidence,
            productsById,
            usedProductEvidenceIds = null
        ) {
            const groups = [];
            const visibleIds = new Set(productsById.keys());
            const answerBoundProductEvidence = (
                usedProductEvidenceIds instanceof Set
            );
            const isVisibleOrUnknown = productId => {
                const id = numericProductId(productId);
                return id === null || visibleIds.has(id);
            };

            const claims = Array.isArray(evidence?.merchant_claims?.claims)
                ? evidence.merchant_claims.claims
                : [];
            claims
                .filter(item => (
                    !answerBoundProductEvidence
                    &&
                    item?.claim_scope === 'ordinary'
                    && isVisibleOrUnknown(item?.product_id)
                ))
                .slice(0, 4)
                .forEach(item => pushEvidenceRow(
                    groups,
                    'merchant_claims',
                    '品牌主打',
                    item.display_claim,
                    item.product_id,
                    productsById
                ));

            const selected = Array.isArray(
                evidence?.product_evidence?.packet?.selected
            )
                ? evidence.product_evidence.packet.selected
                : [];
            selected
                .filter(item => {
                    const payload = item?.evidence || item || {};
                    const productId = numericProductId(
                        payload.product_id ?? item?.product_id
                    );
                    const evidenceId = String(
                        payload.evidence_id || ''
                    );
                    return (
                        productId !== null
                        && visibleIds.has(productId)
                        && (
                            !answerBoundProductEvidence
                            || usedProductEvidenceIds.has(evidenceId)
                        )
                    );
                })
                .forEach(item => {
                    const payload = item?.evidence || item || {};
                    const productId = (
                        payload.product_id ?? item?.product_id
                    );
                    pushEvidenceRow(
                        groups,
                        'product_evidence',
                        '商品证据',
                        payload.exact_text || item.exact_text,
                        productId,
                        productsById,
                        {
                            evidenceId: payload.evidence_id,
                            productId
                        }
                    );
                });

            const reviews = Array.isArray(
                evidence?.review_evidence?.results
            )
                ? evidence.review_evidence.results
                : [];
            reviews
                .filter(item => (
                    !answerBoundProductEvidence
                    && isVisibleOrUnknown(item?.product_id)
                ))
                .slice(0, 3)
                .forEach(item => {
                    const firstQuote = (
                        Array.isArray(item?.evidence)
                            ? item.evidence
                            : []
                    ).find(entry => entry?.quote)?.quote;
                    pushEvidenceRow(
                        groups,
                        'review_evidence',
                        '用户反馈',
                        item?.synthesis?.text || firstQuote,
                        item?.product_id,
                        productsById
                    );
                });

            return groups
                .map(group => ({
                    ...group,
                    items: (
                        group.key === 'product_evidence'
                            ? group.items
                            : group.items.slice(0, 3)
                    )
                }))
                .filter(group => group.items.length);
        }

        function createEvidenceLayer(
            documentRef,
            evidence,
            productsById,
            usedProductEvidenceIds = null
        ) {
            const groups = evidenceGroupsForState(
                evidence || {},
                productsById,
                usedProductEvidenceIds
            );
            if (!groups.length) return null;

            const section = documentRef.createElement('section');
            section.className = (
                'guide-presentation-section '
                + 'guide-presentation-evidence'
            );
            section.dataset.sectionKind = 'evidence';

            const title = documentRef.createElement('h3');
            title.textContent = '展示依据';
            section.appendChild(title);

            const grid = documentRef.createElement('div');
            grid.className = 'guide-evidence-grid';
            groups.forEach(group => {
                const block = documentRef.createElement('div');
                block.className = 'guide-evidence-group';
                const label = documentRef.createElement('strong');
                label.className = 'guide-evidence-label';
                label.textContent = group.title;
                const list = documentRef.createElement('ul');
                list.className = 'guide-evidence-list';
                group.items.forEach(item => {
                    const row = documentRef.createElement('li');
                    row.className = 'guide-evidence-item';
                    row.textContent = item.text;
                    if (
                        /^[0-9a-f]{64}$/.test(
                            String(item.evidenceId || '')
                        )
                        && item.productId !== null
                    ) {
                        row.dataset.evidenceId = item.evidenceId;
                        row.dataset.guideProductId = String(
                            item.productId
                        );
                    }
                    list.appendChild(row);
                });
                block.append(label, list);
                grid.appendChild(block);
            });
            section.appendChild(grid);
            return section;
        }

        function usedProductEvidenceIds(view) {
            const ids = new Set();
            view.sections.forEach(section => {
                const factIds = Array.isArray(section.used_fact_ids)
                    ? section.used_fact_ids
                    : [];
                factIds.forEach(factId => {
                    const match = String(factId).match(
                        /^evidence:([0-9a-f]{64})$/
                    );
                    if (match) ids.add(match[1]);
                });
            });
            return ids;
        }

        function renderPresentation(container, state, helpers = {}) {
            if (!container?.ownerDocument) {
                throw new Error('PRESENTATION_CONTAINER_INVALID');
            }
            const view = presentationViewForState(state);
            const documentRef = container.ownerDocument;
            const rootNode = documentRef.createElement('div');
            rootNode.className = 'guide-presentation-root';
            rootNode.dataset.presentationMode = view.mode;

            const productsById = new Map(
                view.products.map(product => [product.id, product])
            );
            const slots = view.sections
                .filter(section => section.kind === 'product')
                .map(section => ({
                    slot_id: section.slot_id,
                    product_id: section.product_id
                }));

            view.sections.forEach((section, index) => {
                if (['pitfalls', 'evidence'].includes(
                    section.kind
                )) {
                    return;
                }
                if (section.kind === 'full_cards') {
                    const shelf = createProductShelf(
                        documentRef,
                        view,
                        productsById,
                        helpers
                    );
                    if (shelf) {
                        rootNode.appendChild(shelf);
                    }
                    return;
                }
                const sectionNode = documentRef.createElement('section');
                sectionNode.className = (
                    `guide-presentation-section `
                    + `guide-presentation-${section.kind}`
                );
                sectionNode.dataset.sectionKind = section.kind;

                let product = null;
                if (section.kind === 'product') {
                    product = productsById.get(section.product_id);
                    if (!product) {
                        throw new Error('PRESENTATION_PRODUCT_MISSING');
                    }
                    sectionNode.id = `guide-product-${section.product_id}`;
                    sectionNode.dataset.guideProductId = String(
                        section.product_id
                    );
                    const title = documentRef.createElement('h3');
                    title.textContent = publicProductName(
                        product,
                        `商品 ${index + 1}`
                    );
                    sectionNode.append(
                        title,
                        createInlineProductCard(
                            documentRef,
                            product,
                            helpers
                        )
                    );
                } else if (
                    section.kind === 'closing'
                    && (
                        view.mode !== 'recommendation'
                        || view.recommendationMode === 'fit'
                    )
                ) {
                    const title = documentRef.createElement('h3');
                    title.textContent = '综合推荐';
                    sectionNode.appendChild(title);
                } else if (section.kind === 'comparison') {
                    const title = documentRef.createElement('h3');
                    title.textContent = '对比结论';
                    sectionNode.appendChild(title);
                } else if (section.kind === 'observation') {
                    const title = documentRef.createElement('h3');
                    title.textContent = '当前观察';
                    sectionNode.appendChild(title);
                }

                if (section.copy_text) {
                    const copy = documentRef.createElement('p');
                    appendCopyTokens(
                        copy,
                        section.copy_text,
                        slots,
                        productsById
                    );
                    sectionNode.appendChild(copy);
                }
                if (section.kind === 'comparison') {
                    const comparisonTable = createComparisonTable(
                        documentRef,
                        view.comparisonRows,
                        view.fullCardIds,
                        productsById
                    );
                    if (comparisonTable) {
                        sectionNode.appendChild(comparisonTable);
                    }
                    const winner = createWinnerConclusion(
                        documentRef,
                        view.winner,
                        productsById
                    );
                    if (winner) {
                        sectionNode.appendChild(winner);
                    }
                }
                if (
                    section.kind === 'closing'
                    && view.recommendationMode === 'fit'
                    && view.winner?.status === 'selected'
                ) {
                    const winner = createWinnerConclusion(
                        documentRef,
                        view.winner,
                        productsById,
                        ''
                    );
                    if (winner) {
                        sectionNode.appendChild(winner);
                    }
                }

                if (section.kind === 'product') {
                    const facts = createDirectFacts(
                        documentRef,
                        section.direct_facts
                    );
                    if (facts.childNodes.length) {
                        sectionNode.appendChild(facts);
                    }
                    if (section.advisor_reason) {
                        const reason = documentRef.createElement('p');
                        reason.className = (
                            'guide-product-advisor-reason'
                        );
                        const label = documentRef.createElement('strong');
                        label.textContent = '小 ro 的推荐理由：';
                        reason.append(
                            label,
                            documentRef.createTextNode(
                                section.advisor_reason
                            )
                        );
                        sectionNode.appendChild(reason);
                    }
                }
                rootNode.appendChild(sectionNode);
            });
            const evidenceLayer = (
                view.mode === 'product_knowledge'
                    ? createEvidenceLayer(
                        documentRef,
                        state?.evidence,
                        productsById,
                        usedProductEvidenceIds(view)
                    )
                    : null
            );
            if (evidenceLayer) {
                rootNode.appendChild(evidenceLayer);
            }
            container.replaceChildren(rootNode);
            helpers.refreshIcons?.();
            return view;
        }

        async function streamPresentation(
            container,
            state,
            options = {}
        ) {
            if (!container?.ownerDocument) {
                throw new Error('PRESENTATION_CONTAINER_INVALID');
            }
            const view = presentationViewForState(state);
            const documentRef = container.ownerDocument;
            const rootNode = documentRef.createElement('div');
            rootNode.className = 'guide-presentation-root';
            rootNode.dataset.presentationMode = view.mode;
            container.replaceChildren(rootNode);

            const productsById = new Map(
                view.products.map(product => [product.id, product])
            );
            const slots = view.sections
                .filter(section => section.kind === 'product')
                .map(section => ({
                    slot_id: section.slot_id,
                    product_id: section.product_id
                }));
            const delay = Math.max(
                0,
                Number(options.characterDelayMs ?? 28)
            );
            const sleep = options.sleep || (
                milliseconds => new Promise(
                    resolve => setTimeout(resolve, milliseconds)
                )
            );
            let emittedFirstCharacter = false;

            const emitCharacter = async (parent, character) => {
                parent.appendChild(
                    parent.ownerDocument.createTextNode(character)
                );
                if (!emittedFirstCharacter) {
                    emittedFirstCharacter = true;
                    options.onFirstCharacter?.();
                }
                if (delay > 0) await sleep(delay);
            };

            const emitCopy = async (parent, text) => {
                const tokens = substituteProductSlots(text, slots);
                for (const token of tokens) {
                    if (token.type === 'text') {
                        for (const character of token.value) {
                            await emitCharacter(parent, character);
                        }
                        continue;
                    }
                    const product = productsById.get(token.product_id);
                    if (!product) {
                        throw new Error(
                            'PRESENTATION_PRODUCT_MISSING'
                        );
                    }
                    const button = documentRef.createElement('button');
                    button.type = 'button';
                    button.className = 'guide-product-ref';
                    button.dataset.guideProductRef = String(
                        token.product_id
                    );
                    button.textContent = publicProductName(
                        product,
                        `商品 ${token.product_id}`
                    );
                    parent.appendChild(button);
                }
            };

            for (
                let index = 0;
                index < view.sections.length;
                index += 1
            ) {
                const section = view.sections[index];
                if (['pitfalls', 'evidence'].includes(
                    section.kind
                )) {
                    continue;
                }
                if (section.kind === 'full_cards') {
                    const shelf = createProductShelf(
                        documentRef,
                        view,
                        productsById,
                        options
                    );
                    if (shelf) {
                        rootNode.appendChild(shelf);
                    }
                    continue;
                }
                const sectionNode = documentRef.createElement('section');
                sectionNode.className = (
                    `guide-presentation-section `
                    + `guide-presentation-${section.kind}`
                );
                sectionNode.dataset.sectionKind = section.kind;

                if (section.kind === 'product') {
                    const product = productsById.get(
                        section.product_id
                    );
                    if (!product) {
                        throw new Error(
                            'PRESENTATION_PRODUCT_MISSING'
                        );
                    }
                    sectionNode.id = (
                        `guide-product-${section.product_id}`
                    );
                    sectionNode.dataset.guideProductId = String(
                        section.product_id
                    );
                    const title = documentRef.createElement('h3');
                    title.textContent = publicProductName(
                        product,
                        `商品 ${index + 1}`
                    );
                    const card = createInlineProductCard(
                        documentRef,
                        product,
                        options
                    );
                    sectionNode.append(title, card);
                    rootNode.appendChild(sectionNode);
                    options.onInlineCard?.(section.product_id);
                } else {
                    const titleByKind = {
                        closing: (
                            view.mode !== 'recommendation'
                            || view.recommendationMode === 'fit'
                        )
                            ? '综合推荐'
                            : null,
                        comparison: '对比结论',
                        observation: '当前观察'
                    };
                    const titleText = titleByKind[section.kind];
                    if (titleText) {
                        const title = documentRef.createElement('h3');
                        title.textContent = titleText;
                        sectionNode.appendChild(title);
                    }
                    rootNode.appendChild(sectionNode);
                }

                if (section.copy_text) {
                    const copy = documentRef.createElement('p');
                    sectionNode.appendChild(copy);
                    await emitCopy(copy, section.copy_text);
                }
                if (section.kind === 'comparison') {
                    const comparisonTable = createComparisonTable(
                        documentRef,
                        view.comparisonRows,
                        view.fullCardIds,
                        productsById
                    );
                    if (comparisonTable) {
                        sectionNode.appendChild(comparisonTable);
                    }
                    const winner = createWinnerConclusion(
                        documentRef,
                        view.winner,
                        productsById
                    );
                    if (winner) {
                        sectionNode.appendChild(winner);
                    }
                }
                if (
                    section.kind === 'closing'
                    && view.recommendationMode === 'fit'
                    && view.winner?.status === 'selected'
                ) {
                    const winner = createWinnerConclusion(
                        documentRef,
                        view.winner,
                        productsById,
                        ''
                    );
                    if (winner) {
                        sectionNode.appendChild(winner);
                    }
                }

                if (section.kind === 'product') {
                    const facts = createDirectFacts(
                        documentRef,
                        section.direct_facts
                    );
                    if (facts.childNodes.length) {
                        sectionNode.appendChild(facts);
                    }
                    if (section.advisor_reason) {
                        const reason = documentRef.createElement('p');
                        reason.className = (
                            'guide-product-advisor-reason'
                        );
                        const label = documentRef.createElement('strong');
                        label.textContent = '小 ro 的推荐理由：';
                        reason.appendChild(label);
                        sectionNode.appendChild(reason);
                        await emitCopy(
                            reason,
                            section.advisor_reason
                        );
                    }
                }

            }
            const evidenceLayer = (
                view.mode === 'product_knowledge'
                    ? createEvidenceLayer(
                        documentRef,
                        state?.evidence,
                        productsById,
                        usedProductEvidenceIds(view)
                    )
                    : null
            );
            if (evidenceLayer) {
                rootNode.appendChild(evidenceLayer);
            }
            options.refreshIcons?.();
            return view;
        }

        function thinkingStagesForMode(mode) {
            return [
                ...(THINKING_STAGES[mode] || THINKING_STAGES.recommend)
            ];
        }

        function renderThinking(controller) {
            if (!controller?.element) return;
            const documentRef = controller.element.ownerDocument;
            const stage = controller.stages[controller.current] || '';
            const stageNode = documentRef.createElement('div');
            stageNode.className = 'guide-thinking-stage';

            const label = documentRef.createElement('span');
            label.className = 'guide-thinking-stage-label';
            label.textContent = (
                controller.summary
                || STAGE_LABELS[stage]
                || '正在整理这次回答'
            );
            stageNode.appendChild(label);

            const markers = documentRef.createElement('div');
            markers.className = 'guide-thinking-markers';
            controller.stages.forEach((item, index) => {
                const marker = documentRef.createElement('span');
                marker.className = 'guide-thinking-marker';
                marker.dataset.stage = item;
                marker.dataset.state = (
                    index < controller.current
                        ? 'done'
                        : index === controller.current
                            ? 'active'
                            : 'pending'
                );
                markers.appendChild(marker);
            });
            controller.element.replaceChildren(stageNode, markers);
        }

        function createThinkingPipeline(container, options = {}) {
            if (!container?.ownerDocument) return null;
            const stages = thinkingStagesForMode(
                options.mode || 'recommend'
            );
            if (!stages.length) return null;
            const element = container.ownerDocument.createElement('div');
            element.className = 'guide-thinking-pipeline';
            element.setAttribute('role', 'status');
            element.setAttribute('aria-live', 'polite');
            const controller = {
                element,
                mode: options.mode || 'recommend',
                stages,
                current: 0,
                summary: '',
                autoAdvanceMs: Number(options.autoAdvanceMs || 0),
                autoAdvanceTimer: null
            };
            if (
                options.beforeNode
                && options.beforeNode.parentNode === container
            ) {
                container.insertBefore(element, options.beforeNode);
            } else {
                container.appendChild(element);
            }
            renderThinking(controller);
            scheduleThinkingAutoAdvance(controller);
            return controller;
        }

        function clearThinkingAutoAdvance(controller) {
            if (!controller?.autoAdvanceTimer) return;
            if (typeof clearTimeout === 'function') {
                clearTimeout(controller.autoAdvanceTimer);
            }
            controller.autoAdvanceTimer = null;
        }

        function scheduleThinkingAutoAdvance(controller) {
            if (
                !controller?.element
                || !controller.stages?.length
                || !Number.isFinite(controller.autoAdvanceMs)
                || controller.autoAdvanceMs <= 0
                || controller.current >= controller.stages.length - 1
                || typeof setTimeout !== 'function'
            ) {
                return;
            }
            clearThinkingAutoAdvance(controller);
            controller.autoAdvanceTimer = setTimeout(() => {
                controller.autoAdvanceTimer = null;
                if (!controller.element?.isConnected) return;
                controller.current = Math.min(
                    controller.current + 1,
                    controller.stages.length - 1
                );
                controller.summary = '';
                renderThinking(controller);
                scheduleThinkingAutoAdvance(controller);
            }, controller.autoAdvanceMs);
        }

        function setThinkingMode(controller, mode) {
            if (!controller?.element) return controller;
            const stages = thinkingStagesForMode(mode);
            if (!stages.length) return controller;
            clearThinkingAutoAdvance(controller);
            controller.mode = mode;
            controller.stages = stages;
            controller.current = 0;
            controller.summary = '';
            renderThinking(controller);
            scheduleThinkingAutoAdvance(controller);
            return controller;
        }

        function advanceThinkingPipeline(
            controller,
            stage,
            summary = ''
        ) {
            if (!controller?.element || !controller.stages.length) {
                return controller;
            }
            const normalized = String(stage || '');
            const exactIndex = controller.stages.indexOf(normalized);
            controller.current = (
                exactIndex >= 0
                    ? Math.max(controller.current, exactIndex)
                    : Math.min(
                        controller.current + 1,
                        controller.stages.length - 1
                    )
            );
            controller.summary = String(summary || '');
            renderThinking(controller);
            if (controller.current >= controller.stages.length - 1) {
                clearThinkingAutoAdvance(controller);
            }
            return controller;
        }

        function dismissThinkingPipeline(
            controller,
            options = {}
        ) {
            if (!controller?.element) return;
            clearThinkingAutoAdvance(controller);
            const element = controller.element;
            element.dataset.firstCharacter = (
                options.firstCharacter === true ? 'true' : 'false'
            );
            element.classList.add('is-leaving');
            const remove = () => {
                if (element.isConnected) element.remove();
                controller.element = null;
            };
            if (typeof setTimeout === 'function') {
                setTimeout(remove, 320);
            } else {
                remove();
            }
        }

        return Object.freeze({
            createTurnState,
            reduceGuideEvent,
            resolveVisibleProducts,
            substituteProductSlots,
            serializePresentation,
            restorePresentation,
            renderRecommendationPresentation,
            renderComparisonPresentation,
            renderSingleProductPresentation,
            renderProductKnowledgePresentation,
            renderGeneralKnowledgePresentation,
            renderFollowupPresentation,
            renderImagePresentation,
            renderConsultationPresentation,
            renderClarificationPresentation,
            renderErrorPresentation,
            renderPresentation,
            streamPresentation,
            thinkingStagesForMode,
            createThinkingPipeline,
            setThinkingMode,
            advanceThinkingPipeline,
            dismissThinkingPipeline
        });
    }
);
