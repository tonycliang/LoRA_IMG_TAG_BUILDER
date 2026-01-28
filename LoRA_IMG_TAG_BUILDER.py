import json
import logging
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import List, Dict, Any

import PySimpleGUI as sg
from PIL import Image

# -------------------------- 全局配置 --------------------------
LOG_ON: bool = False # 调试=True，发布=False
DEFAULT_FOLDER: str = ""
SUPPORTED_FORMATS: tuple = (".png", ".jpg", ".jpeg")
TABLE_HEADERS: list = ["频率", "提示词"]
TABLE_SIZE: tuple = (20, 20)
# 新增：目录记录配置
HISTORY_FILE = Path("folder_history.json")  # 用Pathlib管理记录文件


# -------------------------- 日志配置 --------------------------
def setup_logging() -> None:
    log_level = logging.DEBUG if LOG_ON else logging.CRITICAL
    log_format = "%(asctime)s - %(levelname)s - %(module)s - %(message)s"
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("lora_tag_tool.log", encoding="utf-8", mode="a")
        ]
    )


setup_logging()
logger = logging.getLogger(__name__)


# -------------------------- 新增：目录记录相关函数（全Pathlib实现） --------------------------
def load_folder_history() -> List[str]:
    """读取目录记录文件，校验有效性，返回时间逆序的有效目录列表（纯Pathlib实现）"""
    history = []
    try:
        if HISTORY_FILE.exists():  # Pathlib原生exists()
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                history = data.get("history", [])

        # 步骤1：校验目录是否存在，过滤无效项（Pathlib原生is_dir()）
        valid_history = []
        for folder_str in history:
            folder = Path(folder_str)
            if folder.is_dir():  # 替换os.path.isdir()
                valid_history.append(folder_str)

        # 步骤2：去重（保留第一次出现的，因为是逆序，即最新的）
        unique_history = []
        seen = set()
        for folder in valid_history:
            if folder not in seen:
                seen.add(folder)
                unique_history.append(folder)

        return unique_history[:10]  # 只保留最近10条
    except Exception as e:
        logger.error(f"加载目录记录失败：{str(e)}", exc_info=LOG_ON)
        return []


def save_folder_history(folder_str: str) -> None:
    """将新目录加入记录，去重+时间逆序+保留最新10条，写入JSON文件（纯Pathlib实现）"""
    folder = Path(folder_str)
    if not folder.is_dir():  # 替换os.path.isdir()
        return  # 非有效目录不记录

    # 读取现有记录
    history = load_folder_history()

    # 步骤1：将新目录放到最前面（时间逆序）
    if folder_str in history:
        history.remove(folder_str)  # 先删除旧的，再插前面
    history.insert(0, folder_str)

    # 步骤2：去重+严格限制最多10条
    unique_history = []
    seen = set()
    for f in history:
        if f not in seen:
            seen.add(f)
            unique_history.append(f)
    final_history = unique_history[:10]  # 强制只保留前10条

    # 步骤3：写入JSON文件（Pathlib路径直接用）
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"history": final_history}, f, ensure_ascii=False, indent=2)
        logger.info(f"目录记录已更新：{folder_str} | 当前记录总数：{len(final_history)}")
    except Exception as e:
        logger.error(f"保存目录记录失败：{str(e)}", exc_info=LOG_ON)


# -------------------------- 文本格式统一+顺序去重处理函数 --------------------------
def normalize_caption_text(text: str) -> str:
    """
    统一标注文本格式：
    1. 中文逗号、顿号替换为英文逗号
    2. 中文括号/引号替换为英文半角
    3. 斜杠/反斜杠替换为英文逗号
    4. 去重空格、换行，首尾去空
    5. 保留顺序的Tag去重
    """
    if not text:
        return ""
    try:
        # 替换中文标点为英文半角
        replace_map = {
            '，': ',', '、': ',', '/': ',', '\\': ',',
            '（': '(', '）': ')', '“': '"', '”': '"',
            '‘': "'", '’': "'", '；': ';', '：': ':'
        }
        normalized = text
        for old_char, new_char in replace_map.items():
            normalized = normalized.replace(old_char, new_char)

        # 去重空格、换行，首尾去空
        normalized = normalized.replace("\n", "").replace(" ", "").strip()

        # 保留顺序的Tag去重
        if normalized:
            tag_list = [t.strip() for t in normalized.split(",") if t.strip()]
            seen = dict()
            unique_tag_list = []
            for tag in tag_list:
                if tag not in seen:
                    seen[tag] = True
                    unique_tag_list.append(tag)
            normalized = ",".join(unique_tag_list)

        logger.debug(f"文本格式统一+去重完成：原文本[{text[:50]}...] → 处理后[{normalized[:50]}...]")
        return normalized
    except Exception as e:
        logger.error(f"文本格式统一+去重失败：{str(e)}", exc_info=LOG_ON)
        return text


# -------------------------- 核心类：图片标注项 --------------------------
class ImageCaptionItem:
    def __init__(self, img_path: Path):
        self.img_path: Path = img_path
        self.txt_path: Path = img_path.with_suffix(".txt")
        self.filename: str = img_path.name
        self.resolution: str = self._get_resolution()
        self.caption: str = self.load_caption()
        logger.info(f"初始化图片标注项：{self.filename} | 分辨率：{self.resolution}")

    def _get_resolution(self) -> str:
        try:
            with Image.open(str(self.img_path)) as img:
                resolution = f"{img.size[0]}×{img.size[1]}"
            logger.debug(f"读取{self.filename}分辨率成功：{resolution}")
            return resolution
        except Exception as e:
            logger.error(f"读取{self.filename}分辨率失败：{str(e)}", exc_info=LOG_ON)
            return "未知"

    def load_caption(self) -> str:
        try:
            if self.txt_path.exists():  # Pathlib原生exists()
                raw_caption = self.txt_path.read_text(encoding="utf-8")
                caption = normalize_caption_text(raw_caption)
                log_msg = f"加载{self.filename}标注：{caption[:50]}..." if len(
                    caption) > 50 else f"加载{self.filename}标注：{caption}"
                logger.debug(log_msg)
                return caption
            logger.debug(f"{self.filename}无标注文件，返回空内容")
            return ""
        except Exception as e:
            logger.error(f"加载{self.filename}标注失败：{str(e)}", exc_info=LOG_ON)
            return ""

    def save_caption(self, content: str) -> str:
        try:
            clean_content = normalize_caption_text(content)
            self.txt_path.write_text(clean_content, encoding="utf-8")
            self.caption = clean_content
            log_msg = f"保存{self.filename}标注：{clean_content[:50]}..." if len(
                clean_content) > 50 else f"保存{self.filename}标注：{clean_content}"
            logger.info(log_msg)
            return clean_content
        except Exception as e:
            logger.error(f"保存{self.filename}标注失败：{str(e)}", exc_info=LOG_ON)
            return ""

    def get_info(self) -> str:
        return f"文件名：{self.filename} | 分辨率：{self.resolution}"


# -------------------------- 核心类：Tag辅助工具 --------------------------
class TagAssistant:
    def __init__(self, target_folder: Path = None):
        self.target_folder = target_folder
        self.tag_counts: defaultdict[str, int] = defaultdict(int)
        self.history_file = self.target_folder / "lora_tag_history.json" if self.target_folder else Path(
            "lora_tag_history.json")
        self.load_history()  # 初始化时加载对应目录的Tag历史
        logger.info(f"初始化Tag辅助工具，历史文件：{self.history_file.absolute()}")

    def update_target_folder(self, new_folder: Path) -> None:
        """更新目标文件夹，重置Tag统计，加载新目录的Tag历史"""
        self.target_folder = new_folder
        self.history_file = new_folder / "lora_tag_history.json"
        # 核心：清空原有统计，重新加载新目录的Tag历史
        self.tag_counts.clear()
        self.load_history()
        logger.info(f"更新目标文件夹：{new_folder.absolute()}，Tag历史文件路径同步更新为：{self.history_file.absolute()}")

    def load_history(self) -> None:
        """加载当前目标文件夹的Tag历史，无文件则清空统计"""
        try:
            if self.history_file.exists():  # Pathlib原生exists()
                self.tag_counts = defaultdict(int, json.loads(self.history_file.read_text(encoding="utf-8")))
                logger.info(f"加载Tag历史成功：{self.history_file.absolute()} | 共{len(self.tag_counts)}个常用提示词")
            else:
                # 核心：无历史文件则清空统计
                self.tag_counts.clear()
                logger.debug(f"Tag历史文件不存在：{self.history_file.absolute()}，已清空统计")
        except Exception as e:
            logger.error(f"加载Tag历史失败：{str(e)}", exc_info=LOG_ON)
            self.tag_counts.clear()  # 加载失败也清空

    def save_history(self) -> None:
        try:
            if not self.target_folder:
                logger.warning("未设置目标文件夹，跳过Tag历史保存")
                return
            sorted_tags: Dict[str, int] = {
                k: v for k, v in sorted(self.tag_counts.items(), key=lambda x: x[1], reverse=True)
                if k.strip()
            }
            self.history_file.write_text(
                json.dumps(sorted_tags, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.info(f"保存Tag历史成功：{self.history_file.absolute()} | 共{len(sorted_tags)}个常用提示词")
        except Exception as e:
            logger.error(f"保存Tag历史失败：{str(e)}", exc_info=LOG_ON)

    def update_tags(self, caption: str) -> None:
        if not caption:
            logger.debug("标注内容为空，跳过Tag统计更新")
            return
        try:
            normalized_caption = normalize_caption_text(caption)
            tags: List[str] = [t.strip() for t in normalized_caption.split(",") if t.strip()]
            for tag in tags:
                self.tag_counts[tag] += 1
            logger.debug(f"更新Tag统计：新增{len(tags)}个提示词，当前总计{len(self.tag_counts)}个")
        except Exception as e:
            logger.error(f"更新Tag统计失败：{str(e)}", exc_info=LOG_ON)

    def re统计_tag_from_folder(self) -> None:
        if not self.target_folder:
            sg.popup("未选择打标文件夹，无法重新统计！", title="提示")
            logger.warning("重新统计Tag失败：未设置目标文件夹")
            return

        self.tag_counts.clear()
        logger.info(f"开始重新统计{self.target_folder.absolute()}下所有标注文件的Tag")

        txt_files = list(self.target_folder.glob("*.txt"))
        if not txt_files:
            sg.popup(f"目标文件夹下无txt标注文件！", title="提示")
            logger.info(f"重新统计完成：目标文件夹下无txt文件，Tag统计为空")
            self.save_history()
            return

        total_files = len(txt_files)
        processed = 0
        for txt_file in txt_files:
            try:
                raw_text = txt_file.read_text(encoding="utf-8")
                normalized_text = normalize_caption_text(raw_text)
                tags = [t.strip() for t in normalized_text.split(",") if t.strip()]
                for tag in tags:
                    self.tag_counts[tag] += 1
                processed += 1
                logger.debug(f"统计{txt_file.name}：解析出{len(tags)}个去重后Tag")
            except Exception as e:
                logger.error(f"统计{txt_file.name}失败：{str(e)}", exc_info=LOG_ON)

        self.save_history()
        sg.popup(f"重新统计完成！\n共处理{processed}/{total_files}个标注文件\n总计{len(self.tag_counts)}个不同Tag",
                 title="统计完成")
        logger.info(f"重新统计完成：处理{processed}/{total_files}个文件，总计{len(self.tag_counts)}个不同Tag")

    def get_sorted_tags(self) -> List[List[Any]]:
        """获取按频率降序排列的Tag列表，无数据则返回空列表"""
        sorted_tags = [[v, k] for k, v in sorted(self.tag_counts.items(), key=lambda x: x[1], reverse=True) if
                       k.strip()]
        logger.debug(f"获取排序后Tag列表：共{len(sorted_tags)}个提示词")
        return sorted_tags

    def insert_tag(self, current_content: str, tag: str) -> str:
        try:
            current_content = normalize_caption_text(current_content)
            current_tags: List[str] = [t.strip() for t in current_content.split(",") if t.strip()]
            if tag not in current_tags:
                current_tags.append(tag)
                logger.debug(f"插入提示词：{tag} | 当前标注列表：{current_tags}")
            else:
                logger.debug(f"提示词已存在，跳过插入：{tag}")
            new_content = normalize_caption_text(",".join(current_tags))
            return new_content
        except Exception as e:
            logger.error(f"插入提示词失败：{str(e)}", exc_info=LOG_ON)
            return current_content


# -------------------------- 兼容旧版本的图片处理函数 --------------------------
def pil_image_to_sg_data(img: Image.Image) -> bytes:
    try:
        bio = BytesIO()
        img.save(bio, format="PNG")
        return bio.getvalue()
    except Exception as e:
        logger.error(f"转换PIL图片为SG格式失败：{str(e)}", exc_info=LOG_ON)
        return b""


def resize_image_keep_ratio(img: Image.Image, target_size=(450, 450), bg_color=(240, 240, 240)) -> Image.Image:
    """全版本兼容：等比缩放图片，空白处填充背景色，不拉伸变形"""
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # 全版本兼容PIL缩放算法
    try:
        img.thumbnail(target_size, Image.Resampling.LANCZOS)
    except AttributeError:
        try:
            img.thumbnail(target_size, Image.ANTIALIAS)
        except AttributeError:
            img.thumbnail(target_size)

    new_img = Image.new("RGB", target_size, bg_color)
    offset_x = (target_size[0] - img.width) // 2
    offset_y = (target_size[1] - img.height) // 2
    new_img.paste(img, (offset_x, offset_y))

    return new_img


# -------------------------- UI主逻辑 --------------------------
def main() -> None:
    logger.info("启动LoRA图片标记工具（调试模式）" if LOG_ON else "启动LoRA图片标记工具（发布模式）")

    tag_assistant = TagAssistant()
    image_items: List[ImageCaptionItem] = []
    current_index: int = -1

    # 加载目录历史
    folder_history = load_folder_history()

    # UI布局
    sg.theme("Default1")
    layout: List[List[Any]] = [
        [
            sg.Combo(
                values=folder_history,
                default_value="",  # 默认值为空
                key="-FOLDER-",
                size=(70, 1),
                tooltip="选择/输入LoRA训练图片所在文件夹（支持下拉选择历史目录）",
                enable_events=False,
                readonly=False
            ),
            sg.FolderBrowse("浏览", key="-BROWSE-"),
            sg.Button("打开文件夹", key="-OPEN-", button_color="green")
        ],
        [
            sg.Column([
                [sg.Push()],
                [
                    sg.Image(
                        key="-IMAGE-",
                        size=(450, 450),
                        tooltip="图片预览（自适应缩放）"
                    )
                ],
                [sg.Push()]
            ], size=(480, 480), pad=(0, 0), element_justification='center'),

            sg.Column([
                [sg.Text("常用提示词 (点击/多选插入)", size=(10, 1), pad=(0, 0))],
                [sg.Table(
                    values=[],  # 初始化为空列表
                    headings=TABLE_HEADERS,
                    key="-TAG_TABLE-",
                    num_rows=23,
                    enable_events=True,
                    select_mode=sg.TABLE_SELECT_MODE_EXTENDED,
                    expand_x=False,
                    expand_y=True,
                    auto_size_columns=False,
                    col_widths=[3, 12],
                    max_col_width=30,
                    justification='left',
                    tooltip="按住Ctrl可多选，点击自动插入到标注框"
                )],
                [sg.Push(),
                 sg.Button("刷新Tags", key="-RECOUNT_TAGS-", button_color="orange", pad=(0, 5))]
            ], pad=(0, 0))
        ],
        [sg.Text("未选择文件夹/图片", key="-INFO-", size=(80, 1), tooltip="图片文件名+分辨率")],
        [sg.Multiline(
            "", key="-CAPTION-", size=(88, 5),
            tooltip="输入LoRA标注提示词，自动统一格式+去重（中文标点→英文、去空格）"
        )],
        [
            sg.Button("上一张", key="-PREV-", disabled=True),
            sg.Button("下一张", key="-NEXT-", disabled=True),
            sg.Text("快捷键：PageUp/PageDown 翻页", size=(30, 1)),
            sg.Text("进度：0/0", key="-PROGRESS-", size=(10, 1))
        ],
        [sg.Push(), sg.Button('退出', key='-EXIT-')]
    ]

    window: sg.Window = sg.Window("LoRA图片标记工具", layout, finalize=True)
    window.bind("<Prior>", "-PREV-")
    window.bind("<Next>", "-NEXT-")
    logger.info("UI窗口初始化完成，进入事件循环")

    # 辅助函数
    def update_image_display(item: ImageCaptionItem) -> None:
        try:
            img = Image.open(str(item.img_path))
            img = resize_image_keep_ratio(img, (450, 450), bg_color=(240, 240, 240))
            img_data = pil_image_to_sg_data(img)
            sg.Image.update(window["-IMAGE-"], data=img_data)
            logger.debug(f"更新{item.filename}图片预览成功")
        except Exception as e:
            logger.error(f"更新{item.filename}图片预览失败：{str(e)}", exc_info=LOG_ON)
            sg.Image.update(window["-IMAGE-"], data="")
        window["-INFO-"].update(item.get_info())
        window["-CAPTION-"].update(item.caption)

    def update_progress() -> None:
        total: int = len(image_items)
        window["-PROGRESS-"].update(f"进度：{current_index + 1}/{total}" if total > 0 else "进度：0/0")
        window["-PREV-"].update(disabled=(current_index <= 0))
        window["-NEXT-"].update(disabled=(current_index >= total - 1 if total > 0 else True))

    def refresh_combo_values(current_selected_folder: str) -> None:
        """
        刷新Combo的下拉列表值（读取最新的目录历史）
        :param current_selected_folder: 当前选中的目录，刷新后保持该默认值
        """
        new_history = load_folder_history()
        # 核心修改：刷新values的同时，保持default_value为当前选中的目录
        window["-FOLDER-"].update(
            values=new_history,
            value=current_selected_folder  # 保留当前选中的目录作为默认值
        )
        logger.debug(f"Combo下拉列表已刷新：共{len(new_history)}条有效目录 | 当前选中：{current_selected_folder}")

    # 事件循环
    while True:
        event, values = window.read()

        if event in (sg.WIN_CLOSED, '-EXIT-'):
            logger.info("用户关闭窗口，开始保存最后状态")
            if current_index >= 0 and values["-CAPTION-"] != image_items[current_index].caption:
                clean_content = image_items[current_index].save_caption(values["-CAPTION-"])
                tag_assistant.update_tags(clean_content)
            tag_assistant.save_history()
            break

        if event == "-OPEN-":
            folder_path_str = values["-FOLDER-"].strip()
            if not folder_path_str:
                sg.popup("请输入/选择有效的文件夹路径！", title="提示")
                continue
            folder_path = Path(folder_path_str)
            if not folder_path.is_dir():  # Pathlib原生is_dir()
                sg.popup(f"文件夹不存在：{folder_path_str}", title="错误")
                continue

            # 核心修改：保存目录记录后，刷新Combo并保留当前选中的目录
            save_folder_history(folder_path_str)
            refresh_combo_values(folder_path_str)  # 传入当前选中的目录

            # 更新Tag辅助工具（自动清空旧统计，加载新目录的Tag历史）
            tag_assistant.update_target_folder(folder_path)

            # 加载图片列表
            image_items = [
                ImageCaptionItem(img_path)
                for img_path in sorted(folder_path.glob("*"))
                if img_path.suffix.lower() in SUPPORTED_FORMATS
            ]

            # 更新Table（无Tag历史则显示空）
            window["-TAG_TABLE-"].update(values=tag_assistant.get_sorted_tags())

            if not image_items:
                sg.popup(f"文件夹{folder_path_str}内无支持的图片文件（{SUPPORTED_FORMATS}）", title="提示")
                current_index = -1
                update_progress()
                window["-INFO-"].update("未选择有效图片")
                window["-CAPTION-"].update("")
                sg.Image.update(window["-IMAGE-"], data="")
                continue

            current_index = 0
            update_image_display(image_items[current_index])
            update_progress()
            logger.info(f"成功打开文件夹：{folder_path.absolute()}，加载{len(image_items)}张图片")

        if event in ("-PREV-", "-NEXT-"):
            if current_index >= 0:
                current_item = image_items[current_index]
                if values["-CAPTION-"] != current_item.caption:
                    clean_content = current_item.save_caption(values["-CAPTION-"])
                    tag_assistant.update_tags(clean_content)
                    window["-TAG_TABLE-"].update(values=tag_assistant.get_sorted_tags())
            if event == "-PREV-" and current_index > 0:
                current_index -= 1
            elif event == "-NEXT-" and current_index < len(image_items) - 1:
                current_index += 1
            if image_items:
                update_image_display(image_items[current_index])
                update_progress()

        if event == "-TAG_TABLE-":
            selected_rows = values["-TAG_TABLE-"]
            if not selected_rows:
                logger.debug("未选中任何提示词，跳过插入")
                continue
            current_content = values["-CAPTION-"]
            for row_idx in selected_rows:
                tag = tag_assistant.get_sorted_tags()[row_idx][1]
                current_content = tag_assistant.insert_tag(current_content, tag)
            window["-CAPTION-"].update(current_content)
            logger.info(f"批量插入提示词：共选中{len(selected_rows)}行，更新后标注内容已同步")

        if event == "-RECOUNT_TAGS-":
            tag_assistant.re统计_tag_from_folder()
            window["-TAG_TABLE-"].update(values=tag_assistant.get_sorted_tags())

    window.close()
    logger.info("UI窗口已关闭，工具进程结束")


if __name__ == "__main__":
    main()
