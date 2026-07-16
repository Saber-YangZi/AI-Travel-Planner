"""AI语音绘图工具 - 纯语音控制的绘图应用"""
import streamlit as st

# ---- 页面配置 ----
st.set_page_config(
    page_title="AI语音绘图工具",
    page_icon="🎨",
    layout="wide",
)

# ---- CSS样式 ----
st.markdown("""
<style>
    .main-header {
        font-size: 2rem; font-weight: 700; padding: 0.5rem 0;
        border-bottom: 3px solid #4A90D9; margin-bottom: 1rem;
        text-align: center;
    }
    .instruction-card {
        background: #E3F2FD; border-radius: 10px; padding: 1rem; margin: 0.5rem 0;
    }
    .command-tag {
        background: #BBDEFB; color: #1565C0; padding: 0.2rem 0.5rem; 
        border-radius: 15px; font-size: 0.8rem; margin-right: 0.5rem;
    }
    .canvas-container {
        border: 2px dashed #90CAF9; border-radius: 10px;
        background: white;
    }
</style>
""", unsafe_allow_html=True)

# ---- 会话状态初始化 ----
if "draw_history" not in st.session_state:
    st.session_state.draw_history = []
if "current_color" not in st.session_state:
    st.session_state.current_color = "#FF5722"
if "current_line_width" not in st.session_state:
    st.session_state.current_line_width = 3
if "voice_command" not in st.session_state:
    st.session_state.voice_command = ""

# ---- 支持的绘图指令 ----
SUPPORTED_COMMANDS = {
    "绘制直线": ["画直线", "直线", "画一条线", "画线"],
    "绘制圆形": ["画圆", "圆形", "画一个圆", "圆形"],
    "绘制矩形": ["画矩形", "矩形", "画正方形", "正方形"],
    "绘制三角形": ["画三角形", "三角形"],
    "绘制曲线": ["画曲线", "曲线", "弧线"],
    "清除画布": ["清除", "清空", "擦掉", "重置"],
    "选择颜色": ["红色", "蓝色", "绿色", "黄色", "黑色", "白色", "橙色", "紫色"],
    "调整粗细": ["粗", "细", "粗一点", "细一点"],
}

COLOR_MAP = {
    "红色": "#FF5722",
    "蓝色": "#2196F3",
    "绿色": "#4CAF50",
    "黄色": "#FFEB3B",
    "黑色": "#000000",
    "白色": "#FFFFFF",
    "橙色": "#FF9800",
    "紫色": "#9C27B0",
}

# ---- 语音识别组件 ----
def voice_recognition():
    st.markdown("""
    <script>
    const startListening = () => {
        const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = 'zh-CN';
        
        recognition.onresult = (event) => {
            const command = event.results[0][0].transcript;
            window.parent.postMessage({ type: 'VOICE_COMMAND', data: command }, '*');
        };
        
        recognition.onerror = (event) => {
            console.error('语音识别错误:', event.error);
        };
        
        recognition.start();
    };
    </script>
    """, unsafe_allow_html=True)
    
    if st.button("🎤 开始语音输入", type="primary", use_container_width=True):
        st.session_state.voice_command = "正在听..."
        st.markdown("""
        <script>
        setTimeout(() => {
            if (window.SpeechRecognition || window.webkitSpeechRecognition) {
                startListening();
            } else {
                alert('您的浏览器不支持语音识别功能');
            }
        }, 100);
        </script>
        """, unsafe_allow_html=True)

# ---- 指令解析器 ----
def parse_command(command):
    """解析语音指令"""
    command = command.strip()
    
    # 颜色指令
    for color_name in COLOR_MAP.keys():
        if color_name in command:
            return {"type": "color", "value": COLOR_MAP[color_name], "text": color_name}
    
    # 粗细指令
    if "粗" in command:
        return {"type": "line_width", "value": min(10, st.session_state.current_line_width + 2), "text": "加粗"}
    if "细" in command:
        return {"type": "line_width", "value": max(1, st.session_state.current_line_width - 2), "text": "变细"}
    
    # 清除指令
    for keyword in SUPPORTED_COMMANDS["清除画布"]:
        if keyword in command:
            return {"type": "clear", "value": None, "text": "清除画布"}
    
    # 形状指令
    if any(k in command for k in SUPPORTED_COMMANDS["绘制直线"]):
        return {"type": "shape", "value": "line", "text": "绘制直线"}
    
    if any(k in command for k in SUPPORTED_COMMANDS["绘制圆形"]):
        return {"type": "shape", "value": "circle", "text": "绘制圆形"}
    
    if any(k in command for k in SUPPORTED_COMMANDS["绘制矩形"]):
        return {"type": "shape", "value": "rect", "text": "绘制矩形"}
    
    if any(k in command for k in SUPPORTED_COMMANDS["绘制三角形"]):
        return {"type": "shape", "value": "triangle", "text": "绘制三角形"}
    
    if any(k in command for k in SUPPORTED_COMMANDS["绘制曲线"]):
        return {"type": "shape", "value": "curve", "text": "绘制曲线"}
    
    return {"type": "unknown", "value": command, "text": f"未知指令: {command}"}

# ---- 主UI ----
st.markdown('<div class="main-header">🎨 AI语音绘图工具</div>', unsafe_allow_html=True)

# 说明卡片
st.markdown("""
<div class="instruction-card">
    <h4>💡 使用说明</h4>
    <p>点击下方按钮开始语音输入，说出您想要绘制的图形。</p>
    <p>支持的指令：</p>
    <div>
        <span class="command-tag">画直线</span>
        <span class="command-tag">画圆形</span>
        <span class="command-tag">画矩形</span>
        <span class="command-tag">画三角形</span>
        <span class="command-tag">画曲线</span>
    </div>
    <div style="margin-top: 0.5rem;">
        <span class="command-tag">红色</span>
        <span class="command-tag">蓝色</span>
        <span class="command-tag">绿色</span>
        <span class="command-tag">黄色</span>
        <span class="command-tag">黑色</span>
    </div>
    <div style="margin-top: 0.5rem;">
        <span class="command-tag">粗一点</span>
        <span class="command-tag">细一点</span>
        <span class="command-tag">清除</span>
    </div>
</div>
""", unsafe_allow_html=True)

# 控制面板
col1, col2, col3 = st.columns([1, 2, 1])

with col1:
    st.markdown("### 🎨 颜色选择")
    for color_name, color_code in COLOR_MAP.items():
        if st.button(color_name, key=f"color_{color_name}", 
                     help=f"点击选择{color_name}",
                     disabled=False):
            st.session_state.current_color = color_code
            st.rerun()
    
    st.markdown(f"**当前颜色:** <span style='color:{st.session_state.current_color};font-size:1.5rem'>⬤</span>", 
                unsafe_allow_html=True)

with col2:
    # 画布区域
    st.markdown("### 📄 绘图区域")
    st.markdown("""
    <div class="canvas-container" style="width:100%;height:400px;">
        <canvas id="drawCanvas" width="600" height="400" 
                style="width:100%;height:100%;border:1px solid #ccc;">
        </canvas>
    </div>
    """, unsafe_allow_html=True)
    
    # 语音输入
    voice_recognition()
    
    # 指令显示
    if st.session_state.voice_command:
        st.info(f"🎤 识别到指令: {st.session_state.voice_command}")

with col3:
    st.markdown("### ✏️ 画笔粗细")
    line_width = st.slider("调整粗细", min_value=1, max_value=10, 
                          value=st.session_state.current_line_width)
    if line_width != st.session_state.current_line_width:
        st.session_state.current_line_width = line_width
        st.rerun()
    
    # 快捷按钮
    st.markdown("### ⚡ 快捷操作")
    if st.button("🗑️ 清除画布", use_container_width=True):
        st.session_state.draw_history = []
        st.markdown("""
        <script>
        const canvas = document.getElementById('drawCanvas');
        if (canvas) {
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = 'white';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
        }
        </script>
        """, unsafe_allow_html=True)
    
    # 历史记录
    st.markdown("### 📜 操作历史")
    if st.session_state.draw_history:
        for i, action in enumerate(reversed(st.session_state.draw_history[-5:]), 1):
            st.caption(f"{i}. {action}")
    else:
        st.caption("暂无操作记录")

# ---- Canvas绘图脚本 ----
st.markdown("""
<script>
const canvas = document.getElementById('drawCanvas');
if (canvas) {
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = 'white';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    let isDrawing = false;
    let lastX = 0;
    let lastY = 0;
    let currentTool = 'line';
    let currentColor = '#FF5722';
    let currentWidth = 3;
    
    const getMousePos = (e) => {
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        return {
            x: (e.clientX - rect.left) * scaleX,
            y: (e.clientY - rect.top) * scaleY
        };
    };
    
    const drawLine = (x1, y1, x2, y2) => {
        ctx.beginPath();
        ctx.strokeStyle = currentColor;
        ctx.lineWidth = currentWidth;
        ctx.lineCap = 'round';
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
    };
    
    canvas.addEventListener('mousedown', (e) => {
        isDrawing = true;
        const pos = getMousePos(e);
        lastX = pos.x;
        lastY = pos.y;
    });
    
    canvas.addEventListener('mousemove', (e) => {
        if (!isDrawing) return;
        const pos = getMousePos(e);
        
        if (currentTool === 'line') {
            const tempCanvas = document.createElement('canvas');
            const tempCtx = tempCanvas.getContext('2d');
            tempCanvas.width = canvas.width;
            tempCanvas.height = canvas.height;
            tempCtx.drawImage(canvas, 0, 0);
            drawLine(lastX, lastY, pos.x, pos.y);
            setTimeout(() => {
                ctx.drawImage(tempCanvas, 0, 0);
            }, 100);
        } else {
            drawLine(lastX, lastY, pos.x, pos.y);
            lastX = pos.x;
            lastY = pos.y;
        }
    });
    
    canvas.addEventListener('mouseup', () => {
        isDrawing = false;
    });
    
    canvas.addEventListener('mouseout', () => {
        isDrawing = false;
    });
    
    window.addEventListener('message', (event) => {
        if (event.data.type === 'VOICE_COMMAND') {
            console.log('收到语音指令:', event.data.data);
        }
    });
}
</script>
""", unsafe_allow_html=True)