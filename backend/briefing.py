"""Lossless structural annotations for pasted Chinese research briefings.
These are editorial roles, never verification of the reported facts.
"""
import re

VERSION = 'chinese-briefing-v1'
HEADINGS = r'(?m)^(?:[一二三四五六七八九十]+、[^\n]+|\d+\. [^\n]+|机构持仓雷达|今日金融知识卡[^\n]*|AI机制卡[^\n]*|本周知识回顾|本周机构持仓回顾|趋势总结)'
MARKERS = {'相比前次新增：':'novelty_context', '影响判断：':'interpretation',
           '历史类比：':'historical_analogy', '下一验证点':'validation_watch',
           '自测：':'learning_question', '答案：':'learning_answer'}


def annotate(text):
    headings=list(re.finditer(HEADINGS,text))
    boundaries=[(0,'preamble')]+[(m.start(),m.group()) for m in headings]
    sections=[]
    for i,(start,title) in enumerate(boundaries):
        end=boundaries[i+1][0] if i+1<len(boundaries) else len(text)
        if start==end: continue
        raw=text[start:end]
        markers=[]
        for label,role in MARKERS.items():
            for m in re.finditer(re.escape(label),raw):
                markers.append(dict(role=role,start=start+m.start(),end=start+m.end(),text=m.group()))
        citations=[m.group() for m in re.finditer(r'https?://[^\s]+',raw)]
        sections.append(dict(title=title,start=start,end=end,raw_text=raw,
          markers=sorted(markers,key=lambda x:x['start']),source_urls=citations,
          verification_status='needs_primary_source_verification',
          source_labels=[s for s in ['Reuters','Investing.com','美国证券交易委员会','Stock Titan'] if s in raw]))
    return dict(version=VERSION,offset_unit='unicode_codepoint',sections=sections,
      publication_policy='Briefing cutoff is not ingestion time. Never backdate known_at.',
      inference_policy='Interpretations, analogies and validation conditions are not confirmed observations.',
      probability_policy='Narrative confidence and reported novelty are not calibrated investment probabilities.')


def is_briefing(text):
    return '简报' in text[:100] and len(re.findall(r'(?m)^\d+\. ',text))>=2
