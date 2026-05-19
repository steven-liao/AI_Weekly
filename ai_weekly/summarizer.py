"""DeepSeek summarizer — generates Chinese summaries and image prompts."""

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

from ai_weekly.db import Database

logger = logging.getLogger(__name__)


@dataclass
class GeneratedContent:
    article_id: int
    summary_cn: str
    image_prompt: str


class Summarizer:
    """Uses DeepSeek API (OpenAI-compatible) to generate:
    1. Chinese summary (150-300 chars) with optional community insight
    2. English image generation prompt for 通义万相
    """

    SYSTEM_SUMMARIZE = (
        "你是 AI 科技新闻编辑，为小红书读者撰写专业客观的中文摘要。"
        "如果社区评论中有高赞的专家补充、反方观点或重要修正，可以引用到摘要中增强深度。"
    )

    SYSTEM_IMAGE_PROMPT = (
        "You are an AI visual designer. "
        "Convert tech news into concise English image-generation prompts for AI image models. "
        "Style: minimalist isometric 3D render, abstract tech aesthetic. "
        "Color: deep blue/purple with glowing elements. "
        "No text, no watermarks, no faces. Output ONLY the prompt text, nothing else."
    )

    def __init__(self, config):
        self.client = OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url=config.llm.api_base,
        )
        self.model = config.llm.model
        self.max_tokens = config.llm.max_tokens
        self.temperature = config.llm.temperature

    def generate(self, db: Database, ranked_articles: list[dict]) -> list[GeneratedContent]:
        """Generate summaries + image prompts for all articles."""
        results = []
        for art in ranked_articles:
            summary_cn = self._generate_summary(art)
            image_prompt = self._generate_image_prompt(art, summary_cn)
            results.append(GeneratedContent(
                article_id=art["id"],
                summary_cn=summary_cn,
                image_prompt=image_prompt,
            ))
            logger.debug(f"Generated: {art['title'][:40]}... → {summary_cn[:40]}...")
        return results

    def _generate_summary(self, article: dict) -> str:
        prompt = self._build_summary_prompt(article)
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_SUMMARIZE},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=600,
                temperature=self.temperature,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Summary failed: {e}")
            return f"[摘要生成失败] {article.get('title', '')}"

    def _build_summary_prompt(self, article: dict) -> str:
        title = article.get("title", "")
        source = article.get("source", "")
        summary_raw = article.get("summary_raw") or "（无原文摘要）"

        # Include top comments if available
        comments_section = ""
        top_comments_str = article.get("top_comments")
        if top_comments_str:
            try:
                comments_list = json.loads(top_comments_str) if isinstance(top_comments_str, str) else top_comments_str
                if comments_list:
                    lines = [
                        f"  [{c['score']}👍] {c['body'][:300]}"
                        for c in comments_list[:5]
                    ]
                    comments_section = f"\n\n社区高赞评论（参考，有价值的观点可引用到摘要中）：\n" + "\n".join(lines)
            except (json.JSONDecodeError, TypeError):
                pass

        return f"""根据以下资讯信息，生成一段简体中文摘要（150-300字）：

标题：{title}
来源：{source}
原文描述：{summary_raw}{comments_section}

要求：
1. 用简洁专业的中文概括核心内容
2. 如果高赞评论中有专家补充或反方观点，可以引用
3. 说明为什么这条资讯重要或有影响力
4. 保持客观中立，不添加个人观点
5. 语言风格适合小红书科技读者群体"""

    def _generate_image_prompt(self, article: dict, summary_cn: str) -> str:
        prompt = f"Generate an English image-generation prompt for this AI news article:\n\nTitle: {article.get('title', '')}\nSummary: {summary_cn[:300]}"
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_IMAGE_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=200,
                temperature=0.8,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Image prompt failed: {e}")
            return f"A minimalist 3D abstract tech visualization representing: {article.get('title', 'AI news')}"
