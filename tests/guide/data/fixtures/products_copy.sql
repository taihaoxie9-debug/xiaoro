COPY public.knowledge_base (id, title, content, type, product_id, metadata, created_at) FROM stdin;
42	ignore	ignore	product	42	{}	2026-01-01
\.

COPY public.products (id, name, category, brand, price, original_price, description, specifications, image_url, detail_url, platform, stock, sales_count, rating, review_count, created_at, updated_at, specs, tags, skincare_info) FROM stdin;
42	示例\t商品	精华	示例品牌	100.00	\N	描述\n第二行	{"source_tags":{"claim_notes":"brand_marketing","qa_facts":"consumer_qa","shade_note":"official_specs","skin_types":"official_specs","texture":"official_specs"}}	/static/a.png	https://detail.tmall.com/item.htm?id=998532090974	tmall	1	0	\N	0	2026-01-01	2026-01-01	\N	{精华}	{"claim_notes":["立刻年轻十岁"],"key_ingredients":[{"name":"示例成分","source":"opaque source tag"}],"qa_facts":[{"question":"适合谁","answer":"所有人"}],"shade_note":"自然色","texture":"水液","skin_types":["干性"]}
49	示例面霜	面霜	另一品牌	139.00	159.00	普通描述	{}	/static/b.png	https://item.jd.com/100012345678.html	jd	2	3	4.90	5	2026-01-01	2026-01-02	{}	{面霜}	{"suitable_skin_types":["敏感肌"]}
\.

COPY public.knowledge_documents (id, filename, title, file_type, category, product_id, size, chunks_count, content_preview, metadata, created_at, updated_at) FROM stdin;
42	ignore.md	ignore	md	ignore	42	1	1	ignore	{}	2026-01-01	2026-01-01
\.
