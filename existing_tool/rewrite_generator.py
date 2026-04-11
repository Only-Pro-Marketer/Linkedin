"""AI-powered rewrite prompt generator for LinkedIn posts."""

from existing_tool.models import LinkedInPost, PostStructure, PostTemplate


class RewriteGenerator:
    """Generates detailed prompts to rewrite viral posts for a new niche."""

    def generate_prompt(
        self,
        post: LinkedInPost,
        structure: PostStructure,
        target_niche: str = "supplements and food brands",
        tone: str = "authoritative",
        brand_context: str = "",
    ) -> str:
        """Generate a comprehensive rewrite prompt preserving viral mechanics."""

        niche_context = ""
        if brand_context:
            niche_context = f"\nBRAND CONTEXT:\n{brand_context}\n"

        prompt = f"""Rewrite the following viral LinkedIn post for the **{target_niche}** niche.

ORIGINAL POST:
---
{post.content}
---

STRUCTURAL ANALYSIS:
- Hook type: {structure.hook_type.value.replace('_', ' ').title()}
- Hook: "{structure.hook}"
- Body format: {structure.body_format.value}
- CTA type: {structure.cta_type.value.replace('_', ' ').title()}
- Word count: {structure.word_count}
- Uses line breaks: {structure.uses_line_breaks}
- Uses emoji: {structure.uses_emoji}
{niche_context}
REWRITE RULES:
1. Keep the EXACT same structure: {structure.hook_type.value} hook → {structure.body_format.value} body → {structure.cta_type.value} CTA
2. Replace the topic/examples with {target_niche}-specific content
3. Use a {tone} tone
4. Keep approximately {structure.word_count} words (+/- 20%)
5. {"Use line breaks between short lines for readability" if structure.uses_line_breaks else "Use paragraph format"}
6. {"Include relevant emoji sparingly" if structure.uses_emoji else "Do not use emoji"}
7. {"Include 2-3 relevant hashtags" if structure.uses_hashtags else "No hashtags needed"}
8. Make it feel authentic and personal — not templated
9. The hook MUST stop the scroll — make it compelling for {target_niche} professionals
10. Include specific, concrete details relevant to {target_niche} (real challenges, metrics, scenarios)

OUTPUT:
Provide ONLY the rewritten LinkedIn post, ready to copy and paste. No explanations."""

        return prompt

    def generate_prompt_with_template(
        self,
        template: PostTemplate,
        target_niche: str = "supplements and food brands",
        topic: str = "",
        tone: str = "authoritative",
    ) -> str:
        """Generate a rewrite prompt from a template."""

        prompt = f"""Create a LinkedIn post using this viral template for the **{target_niche}** niche.

TEMPLATE: {template.name}

HOOK PATTERN:
{template.hook_pattern}

BODY PATTERN:
{template.body_pattern}

CTA PATTERN:
{template.cta_pattern}

INSTRUCTIONS:
{template.fill_instructions}

{"TOPIC: " + topic if topic else ""}

REQUIREMENTS:
1. Follow the template structure exactly
2. Fill all [PLACEHOLDER] markers with {target_niche}-specific content
3. Use a {tone} tone
4. Make it feel authentic and personal
5. Include specific, concrete details
6. The hook must stop the scroll

OUTPUT:
Provide ONLY the completed LinkedIn post, ready to copy and paste. No explanations."""

        return prompt

    def generate_batch_prompts(
        self,
        posts_with_structures: list,
        target_niche: str = "supplements and food brands",
        tone: str = "authoritative",
    ) -> list:
        """Generate rewrite prompts for multiple posts."""
        prompts = []
        for post, structure in posts_with_structures:
            prompts.append(
                {
                    "author": post.author,
                    "hook_type": structure.hook_type.value,
                    "prompt": self.generate_prompt(post, structure, target_niche, tone),
                }
            )
        return prompts
