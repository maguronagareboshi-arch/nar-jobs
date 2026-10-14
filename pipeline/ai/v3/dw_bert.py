# -*- coding: utf-8 -*-
"""厩舎談話の札を BERT で読む(本番と同じファイル・2026-10-14)。⛔予想の計算には使わない(表示だけ)。
模型 = tohoku-nlp/bert-base-japanese-v3 を、今の規則の下書き 29.6 万件 → エージェントが談話まるごとで付けた札 2.5 万件で仕込んだもの
(研究 src/f5_scripts/dw_bert_train.py・out/dw_bert/report.md)。重みは 16 ビットで置き、CPU で 32 ビットに戻して読む(札は元と 100% 同じ)。
要る部品: torch(CPU)・transformers 5.18・fugashi・unidic-lite。Claude は使わない。
使い方: M = load(dir) → read(M, ['見出し。本文', ...]) → [['S2', 'E2'], ...] → dw_tags.line(...)
本文の形は研究と同じ「見出し。本文」(見出しが無ければ「。本文」)= text(headline, comment)。
"""
from pathlib import Path

import numpy as np

ONE = ('S', 'E')  # 談話に 1 つまで(一番高い 1 つ)


def text(headline, comment):
    """研究の談話の形(out/dw_pat の 30.9 万件と同じ)= 見出し + 「。」 + 本文。"""
    h = headline if isinstance(headline, str) else ''
    c = comment if isinstance(comment, str) else ''
    return f'{h.strip()}。{c.strip()}'


def load(d):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    d = Path(d)
    tok = AutoTokenizer.from_pretrained(d)
    m = AutoModelForSequenceClassification.from_pretrained(d, dtype=torch.float32).eval()
    tags = [m.config.id2label[i] for i in range(m.config.num_labels)]
    return {'tok': tok, 'model': m, 'th': float((d / 'th.txt').read_text(encoding='utf-8')), 'tags': tags}


def probs(M, texts, bs=32):
    import torch
    out = []
    with torch.no_grad():
        for k in range(0, len(texts), bs):
            enc = M['tok'](texts[k:k + bs], padding=True, truncation=True, max_length=160, return_tensors='pt')
            out.append(torch.sigmoid(M['model'](**enc).logits.float()).numpy())
    return np.concatenate(out) if out else np.zeros((0, len(M['tags'])))


def decide(P, tags, th):
    """確率 → 札。S・E は一番高い 1 つ(線を越えた時だけ)。D2 があれば D1 も。"""
    head = [t.rstrip('0123456789') for t in tags]
    res = []
    for p in P:
        got = [tags[j] for j in np.where(p >= th)[0] if head[j] not in ONE]
        for h in ONE:
            js = [j for j in range(len(tags)) if head[j] == h]
            j = max(js, key=lambda j: p[j])
            if p[j] >= th:
                got.append(tags[j])
        if 'D2' in got and 'D1' not in got:
            got.append('D1')
        res.append(got)
    return res


def read(M, texts):
    return decide(probs(M, list(texts)), M['tags'], M['th'])
