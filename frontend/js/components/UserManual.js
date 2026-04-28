/* 操作手册 — Drawer 长文，由 AppHeader 触发 */

(function () {
    var { Drawer, Typography, Divider } = arco;
    var { Paragraph, Title } = Typography;

    function Section({ children, title }) {
        return (
            <section className="user-manual-section">
                <Title heading={6} style={{ margin: '0 0 10px', color: 'var(--ds-text)' }}>{title}</Title>
                <div className="user-manual-section-body">{children}</div>
            </section>
        );
    }

    function UserManualDrawer({ visible, onClose }) {
        return (
            <Drawer
                title={
                    <span>
                        <span className="user-manual-drawer-icon" aria-hidden="true">?</span>
                        操作手册
                    </span>
                }
                visible={visible}
                onCancel={onClose}
                width={Math.min(560, typeof window !== 'undefined' ? window.innerWidth - 24 : 560)}
                footer={null}
                className="user-manual-drawer"
            >
                <div className="user-manual">
                    <Paragraph type="secondary" style={{ marginBottom: 20, fontSize: 13 }}>
                        本页说明 AI 会议转写模块的主要流程与按钮含义。若界面有更新，以实际页面为准。
                    </Paragraph>

                    <Section title="1. 整体流程">
                        <Paragraph>
                            在<strong>会议列表</strong>查看历史记录 → 通过右上角<strong>新建会议</strong>创建任务 → 等待转写与 AI 处理完成 → 在<strong>详情页</strong>查看纪要、导出或同步到实施知识库。
                        </Paragraph>
                    </Section>

                    <Divider style={{ margin: '16px 0' }} />

                    <Section title="2. 会议列表">
                        <Paragraph>
                            <strong>状态</strong>：录音中、转写中、润色/生成纪要中、已完成、失败等；进行中会定时自动刷新。
                        </Paragraph>
                        <Paragraph>
                            <strong>实施知识库</strong>：已同步过纪要的行，标题旁会显示「已同步实施知识库」徽标，可点击打开知识库文档。
                        </Paragraph>
                        <Paragraph>
                            行内菜单可打开飞书文档/多维表格（若已导出）、删除记录等。
                        </Paragraph>
                    </Section>

                    <Divider style={{ margin: '16px 0' }} />

                    <Section title="3. 新建会议（三种方式）">
                        <Paragraph>
                            <strong>实时录音</strong>：浏览器采集麦克风，边录边转写；结束后自动进入润色与纪要生成。
                        </Paragraph>
                        <Paragraph>
                            <strong>上传音频</strong>：上传已有录音文件，由所选 ASR 引擎转写后再走同一套 AI 流程。
                        </Paragraph>
                        <Paragraph>
                            <strong>粘贴 / 上传文本</strong>：直接提供会议文字稿，跳过语音识别；可选关联<strong>实施知识库项目</strong>，便于干系人抽取时合并项目文档中的人名。
                        </Paragraph>
                    </Section>

                    <Divider style={{ margin: '16px 0' }} />

                    <Section title="4. 会议详情页">
                        <Paragraph>
                            <strong>纪要</strong>：支持只读与编辑模式切换；可导出 Markdown、纯文本、HTML、图片（PNG）等。
                        </Paragraph>
                        <Paragraph>
                            <strong>完整转写</strong>：查看润色前后的转写内容。
                        </Paragraph>
                        <Paragraph>
                            <strong>需求清单</strong>：AI 从会议中抽取的需求条目，可按需同步到飞书多维表格（需配置飞书相关环境变量）。
                        </Paragraph>
                        <Paragraph>
                            <strong>干系人图谱</strong>：从本场纪要、转写及参考材料中抽取人物与关系；可切换<strong>卡片 / 关系图 / 手动编辑</strong>；支持同步图谱 Markdown 到实施知识库。
                        </Paragraph>
                        <Paragraph type="secondary" style={{ fontSize: 12 }}>
                            未关联项目时，系统会参考<strong>本库中其它已完成的会议</strong>摘要，辅助识别跨会议重复出现的人员；已关联项目时，优先参考<strong>知识库项目文档</strong>。
                        </Paragraph>
                    </Section>

                    <Divider style={{ margin: '16px 0' }} />

                    <Section title="5. 同步到实施知识库">
                        <Paragraph>
                            详情页可<strong>同步会议纪要</strong>（Markdown）到外部实施知识库；首次需在环境变量中配置知识库地址与账号（详见部署说明）。
                        </Paragraph>
                        <Paragraph>
                            重复同步会先尝试删除旧文档再上传新版本。干系人图谱有独立的「同步图谱」入口，文档类型与纪要区分存放。
                        </Paragraph>
                    </Section>

                    <Divider style={{ margin: '16px 0' }} />

                    <Section title="6. 常见问题">
                        <Paragraph>
                            <strong>一直处理中</strong>：确认后端与 LLM、ASR 配置正常；列表页会轮询刷新，也可进入详情查看状态说明。
                        </Paragraph>
                        <Paragraph>
                            <strong>关系图空白</strong>：需能加载 vis-network 脚本（外网或自建静态资源）；若被拦截，请检查网络或使用本地镜像。
                        </Paragraph>
                        <Paragraph>
                            <strong>端口占用</strong>：后端默认监听配置见 README；Windows 下若 8000 被占用，请结束占用进程或更换端口。
                        </Paragraph>
                    </Section>
                </div>
            </Drawer>
        );
    }

    window.UserManualDrawer = UserManualDrawer;
})();
