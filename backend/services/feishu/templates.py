"""Document content templates for Feishu document formatting.

Provides static methods that generate structured markdown-like content
for different document types. All templates follow consistent styling
conventions for readability.
"""

from __future__ import annotations

from typing import Any, Dict, List


class DocTemplates:
    """Collection of document templates for Feishu document generation.

    Each static method accepts a data dictionary and returns a formatted
    string ready to be used as document content.
    """

    @staticmethod
    def meeting_minutes(meeting_data: Dict[str, Any]) -> str:
        """Generate meeting minutes content in structured markdown format.

        Args:
            meeting_data: Dictionary containing meeting information with keys:
                - title (str): Meeting title.
                - start_time (str): Meeting start time.
                - end_time (str): Meeting end time.
                - attendees (list[str]): List of attendee names.
                - summary (str): Meeting overview / summary.
                - key_points (list[str]): Discussion key points.
                - decisions (list[dict]): Decisions with 'content' and 'owner'.
                - action_items (list[dict]): Action items with 'content',
                  'owner', and optional 'deadline'.
                - full_transcript (str, optional): Complete transcript text.

        Returns:
            Formatted markdown string for document content.
        """
        title: str = meeting_data.get("title", "未命名会议")
        start_time: str = meeting_data.get("start_time", "")
        end_time: str = meeting_data.get("end_time", "")
        attendees: List[str] = meeting_data.get("attendees", [])
        summary: str = meeting_data.get("summary", "")
        key_points: List[str] = meeting_data.get("key_points", [])
        decisions: List[Dict[str, str]] = meeting_data.get("decisions", [])
        action_items: List[Dict[str, str]] = meeting_data.get("action_items", [])
        full_transcript: str = meeting_data.get("full_transcript", "")

        sections: List[str] = []

        # --- Header ---
        sections.append(f"# 会议纪要 - {title}")

        # --- Basic Info ---
        sections.append("## 基本信息")
        sections.append(f"- **会议标题：** {title}")
        if start_time and end_time:
            sections.append(f"- **会议时间：** {start_time} - {end_time}")
        elif start_time:
            sections.append(f"- **会议时间：** {start_time}")
        if attendees:
            sections.append(f"- **参会人员：** {', '.join(attendees)}")

        # --- Summary ---
        if summary:
            sections.append("## 会议概述")
            sections.append(summary)

        # --- Key Points ---
        if key_points:
            sections.append("## 讨论要点")
            for idx, point in enumerate(key_points, 1):
                sections.append(f"{idx}. {point}")

        # --- Decisions ---
        if decisions:
            sections.append("## 决议事项")
            for idx, decision in enumerate(decisions, 1):
                content: str = decision.get("content", "")
                owner: str = decision.get("owner", "")
                if owner:
                    sections.append(f"{idx}. {content}（负责人：{owner}）")
                else:
                    sections.append(f"{idx}. {content}")

        # --- Action Items ---
        if action_items:
            sections.append("## 待办事项")
            for item in action_items:
                content = item.get("content", "")
                owner = item.get("owner", "")
                deadline = item.get("deadline", "")
                line = f"- [ ] {content}"
                if owner:
                    line += f" - 负责人：{owner}"
                if deadline:
                    line += f" - 截止：{deadline}"
                sections.append(line)

        # --- Full Transcript (collapsible) ---
        if full_transcript:
            sections.append("## 完整转写")
            sections.append("<details>")
            sections.append("<summary>点击展开完整转写文本</summary>")
            sections.append("")
            sections.append(full_transcript)
            sections.append("")
            sections.append("</details>")

        return "\n\n".join(sections)

    @staticmethod
    def meeting_doc_title(meeting_data: Dict[str, Any]) -> str:
        """Generate a standard document title for meeting minutes.

        Args:
            meeting_data: Dictionary with 'title' and optionally 'date' keys.

        Returns:
            Formatted title string.
        """
        title: str = meeting_data.get("title", "未命名会议")
        date: str = meeting_data.get("date", meeting_data.get("start_time", ""))
        if date:
            return f"会议纪要 - {title} - {date}"
        return f"会议纪要 - {title}"
