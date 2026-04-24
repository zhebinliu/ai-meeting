/* Minutes export helpers — collect editable DOM, produce MD/Text/HTML/PNG. */
(function () {
    const NS = {};

    function textOf(el) {
        if (!el) return '';
        return (el.textContent || '').replace(/\u00a0/g, ' ').trim();
    }

    function collect(root) {
        if (!root) return null;
        const pick = (sel) => textOf(root.querySelector(`[data-field="${sel}"]`));
        const pickAll = (sel) =>
            Array.from(root.querySelectorAll(`[data-field="${sel}"]`))
                .map(textOf)
                .filter((t) => t);
        return {
            title: pick('title') || '会议纪要',
            date: pick('date'),
            status: pick('status'),
            summary: pick('summary'),
            keyPoints: pickAll('key-point'),
            decisions: pickAll('decision'),
            actionItems: pickAll('action-item'),
        };
    }

    function buildMarkdown(data) {
        const lines = [];
        lines.push(`# ${data.title}`);
        lines.push('');
        if (data.date) lines.push(`**日期：** ${data.date}`);
        if (data.status) lines.push(`**状态：** ${data.status}`);
        lines.push('');
        lines.push('---');
        lines.push('');
        if (data.summary) {
            lines.push('## 会议概要');
            lines.push('');
            lines.push(data.summary);
            lines.push('');
        }
        if (data.keyPoints.length) {
            lines.push('## 讨论要点');
            lines.push('');
            data.keyPoints.forEach((p, i) => lines.push(`${i + 1}. ${p}`));
            lines.push('');
        }
        if (data.decisions.length) {
            lines.push('## 决策事项');
            lines.push('');
            data.decisions.forEach((d, i) => lines.push(`${i + 1}. ${d}`));
            lines.push('');
        }
        if (data.actionItems.length) {
            lines.push('## 待办事项');
            lines.push('');
            data.actionItems.forEach((item, i) => lines.push(`${i + 1}. ${item}`));
            lines.push('');
        }
        lines.push('---');
        lines.push('');
        lines.push(`*导出时间：${new Date().toLocaleString('zh-CN')}*`);
        return lines.join('\n');
    }

    function buildPlainText(data) {
        const lines = [];
        lines.push(data.title);
        lines.push('='.repeat(Math.max(4, data.title.length * 2)));
        lines.push('');
        if (data.date) lines.push(`日期：${data.date}`);
        if (data.status) lines.push(`状态：${data.status}`);
        lines.push('');
        if (data.summary) {
            lines.push('【会议概要】');
            lines.push(data.summary);
            lines.push('');
        }
        if (data.keyPoints.length) {
            lines.push('【讨论要点】');
            data.keyPoints.forEach((p, i) => lines.push(`  ${i + 1}. ${p}`));
            lines.push('');
        }
        if (data.decisions.length) {
            lines.push('【决策事项】');
            data.decisions.forEach((d, i) => lines.push(`  ${i + 1}. ${d}`));
            lines.push('');
        }
        if (data.actionItems.length) {
            lines.push('【待办事项】');
            data.actionItems.forEach((item, i) => lines.push(`  ${i + 1}. ${item}`));
            lines.push('');
        }
        lines.push(`导出时间：${new Date().toLocaleString('zh-CN')}`);
        return lines.join('\n');
    }

    /**
     * Wrap the template DOM into a standalone HTML document with embedded styles,
     * so the downloaded file looks right when opened directly in a browser.
     */
    function buildStandaloneHtml(rootEl, data) {
        const cloned = rootEl.cloneNode(true);
        cloned.querySelectorAll('[contenteditable]').forEach((n) => n.removeAttribute('contenteditable'));
        cloned.querySelectorAll('.mt-delete-btn').forEach((n) => n.remove());

        const styles = `
            body { font-family: "PingFang SC", "Microsoft YaHei", -apple-system, BlinkMacSystemFont, sans-serif; background: #eef2f5; padding: 40px 20px; color: #1f2d3d; }
            * { box-sizing: border-box; }
            .minutes-template { max-width: 960px; margin: 0 auto; background: #fff; border-radius: 20px; box-shadow: 0 20px 40px -15px rgba(0,0,0,0.12); overflow: hidden; }
            .mt-header { padding: 32px 40px; background: linear-gradient(135deg, #0b2b3f 0%, #123d55 100%); color: #fff; }
            .mt-title { font-size: 26px; font-weight: 700; margin-bottom: 18px; border-left: 4px solid #ffc107; padding-left: 16px; }
            .mt-meta { display: flex; flex-wrap: wrap; gap: 12px 24px; font-size: 14px; }
            .mt-meta-item { background: rgba(255,255,255,0.14); padding: 6px 14px; border-radius: 999px; }
            .mt-body { padding: 28px 40px 36px; }
            .mt-section { margin-bottom: 28px; padding-bottom: 22px; border-bottom: 1px solid #e4e9f0; }
            .mt-section:last-child { border-bottom: none; margin-bottom: 0; }
            .mt-section-title { font-size: 18px; font-weight: 700; margin-bottom: 14px; padding-left: 12px; border-left: 4px solid #2c7da0; }
            .mt-summary { background: #f8fbfe; padding: 16px 20px; border-radius: 14px; font-size: 15px; line-height: 1.7; border: 1px solid #e2edf7; }
            .mt-list { list-style: none; padding: 0; margin: 0; }
            .mt-list li { background: #fafcff; border: 1px solid #e9f0f5; border-radius: 12px; padding: 12px 16px; margin-bottom: 10px; font-size: 14px; line-height: 1.6; }
            .mt-list li:last-child { margin-bottom: 0; }
            .mt-empty { color: #9ca3af; font-size: 13px; padding: 8px 0; }
            .mt-footer { padding: 16px 40px; font-size: 12px; color: #6b7280; text-align: right; border-top: 1px solid #f1f5f9; }
        `;
        return [
            '<!DOCTYPE html>',
            '<html lang="zh-CN">',
            '<head>',
            '<meta charset="UTF-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
            `<title>${data.title || '会议纪要'}</title>`,
            `<style>${styles}</style>`,
            '</head>',
            '<body>',
            cloned.outerHTML,
            `<div style="max-width:960px;margin:12px auto 0;padding:8px 20px;font-size:12px;color:#6b7280;text-align:right;">导出时间：${new Date().toLocaleString('zh-CN')}</div>`,
            '</body>',
            '</html>',
        ].join('\n');
    }

    function downloadBlob(content, filename, mime) {
        const blob = new Blob([content], { type: mime });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.download = filename;
        link.href = url;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    async function exportPng(rootEl, filename) {
        if (!window.html2canvas) {
            throw new Error('html2canvas 未加载');
        }
        const canvas = await window.html2canvas(rootEl, {
            backgroundColor: '#ffffff',
            scale: 2,
            useCORS: true,
            logging: false,
        });
        const link = document.createElement('a');
        link.download = filename;
        link.href = canvas.toDataURL('image/png');
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    function todayStamp() {
        const d = new Date();
        const pad = (n) => String(n).padStart(2, '0');
        return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`;
    }

    NS.collect = collect;
    NS.buildMarkdown = buildMarkdown;
    NS.buildPlainText = buildPlainText;
    NS.buildStandaloneHtml = buildStandaloneHtml;
    NS.downloadBlob = downloadBlob;
    NS.exportPng = exportPng;
    NS.todayStamp = todayStamp;

    window.minutesExport = NS;
})();
