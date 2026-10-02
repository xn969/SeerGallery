# Seer Gallery 游戏图片提取 · 0.1.0

[下载 Windows 便携版](https://github.com/xn969/SeerGallery/releases/tag/v0.1.0)

一个 Windows 桌面应用：从 NewSeer 本地 YooAsset 缓存中导出精灵头像、静态全身图，以及背景、地图、剧情插画、UI图标等其他图片。采用 Python 3.12、PySide6 / Qt 6 和 UnityPy，扫描、预览、尺寸识别与提取在后台线程执行。左侧入口为“精灵图片”“其他图片”“设置”。

## 使用

1. 双击 `dist/SeerGallery/SeerGallery.exe`。发布文件夹无需安装 Python，分发时请复制整个 `SeerGallery` 文件夹，不能只复制 exe。
2. 在“设置”中选择自己的 `NewSeer`、`Seer_Data` 或 `yoo` 目录；设置输出目录。默认是 exe 旁的 `output`。
3. 扫描资源。按本体/皮肤筛选，输入编号搜索，勾选需要的行，或点击“选择筛选结果”。隐藏的已选项目仍然保留，选择数量会显示总数。
4. 点击“提取所选 · 双图”。头像与全身图总是同时尝试提取；缺少其中一张时，保留另一张并记录缺失。可在设置中附加半身图。
5. 打开输出文件夹，查看 PNG 与 reports 下的 CSV 结果。再次运行默认跳过有效 PNG，补齐剩余资源；取消后已完成的图片会保留。

输出结构：

```
output/
  pets/1/head.png
  pets/1/body.png
  skins/1400001/head.png
  skins/1400001/body.png
  skins/1400001/half.png   # 可选
  reports/export_时间.csv
  other/DefaultPackage/Assets/Art/Ui/Background/图片名__路径摘要.png
```

## 其他图片导出

1. 点击左侧“其他图片”。默认显示背景与地图场景，可切换到全部其他图片、剧情插画、UI图标。
2. 搜索图片名称或完整路径片段，例如 `cb_mainpanel_bg`、`map/1`、`mainStoryLine`。悬停列表可查看完整源路径。
3. 点击图片行进行预览，显示原始尺寸；“放大预览”可查看更大的预览。
4. 点击“识别尺寸”检查当前筛选范围的原始尺寸，然后选择“宽屏大图 / 全屏候选”。此候选范围是宽≥1000、高≥560、宽高比1.25～2.5的图片；黑色遮罩等也可能满足条件，不能把候选都当作完整背景或界面截图。处在全屏候选筛选时，识别尺寸会检查所有匹配搜索条件的图片。
5. 勾选图片或“选择筛选结果”，点击“导出所选图片”。输出至 `other/资源包/原始目录`，按原始分辨率保存PNG；末尾的短路径摘要避免同名或Windows非法字符引起覆盖。结果记录在 `reports/images_时间.csv`。

尺寸识别结果保留到本次扫描结束；重新扫描会重新读取清单。识别尺寸不会写入游戏目录。一次检查大量资源可能需要较长时间，进度可见且支持取消。跳过已存在PNG、缺失与失败报告同样适用于其他图片。

当前清单识别到35542张非精灵静态图片，按路径归类为1298张背景、2517张场景、2045张剧情/插画、29682张UI/图标。背景目录中也有界面部件，游戏中的完整界面可能由多张图片拼合。此功能导出原始图片，不重建完整界面。扫描包含 DefaultPackage 和可用的 StartupPackage。

## 分类与支持范围

- 按用户提供的资源编号规则：小于10000为本体，大于10000为皮肤；10000归为边界编号。当前本地静态资源没有10000。
- 本体和皮肤都使用 `Assets/Art/Ui/assets/pet/{head,body,half}/{编号}` 路径；皮肤多为六、七位编号。每种图片数量不同，应用按编号合并并显示缺失状态。非数字名字的公共占位图不会进入角色列表。
- 此分类是资源编号规则，尚未提供中文名称、皮肤所属本体映射；不通过画面颜色猜测归属。
- 精灵图是静态全身图，不是动画图集。PNG 保留原始分辨率与透明通道，半身 JPG 转为 PNG 时仍保持原有背景。
- 当前支持已经验证的 NewSeer 紧凑清单格式 `1.5.2` 与未加密的标准 UnityFS 缓存。清单格式变化时会报错，不继续猜测或批量导出错误图片。
- 应用只读取游戏数据；禁止向游戏安装目录写入输出。未下载的缓存只能记录缺失，工具不会联网下载资源。
- 设置保存在当前用户 `HKEY_CURRENT_USER/Software/SeerGallery/Extractor`。大包按哈希分组，每个包一次读取，依照完整资源路径选择 Sprite，避免把同一包的其他编号图片错误导出到目标编号下。

## 开发与验证

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r app\requirements.txt
.\启动开发版.ps1
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\build.ps1
```

后端在 `app/core.py`，主界面在 `app/main.py`，其他图片页面在 `app/other_page.py`。14项测试涵盖本体/皮肤双图、其他图片的尺寸识别与导出、重跑跳过、缺失与损坏资源、取消报告、路径保护、UI导航和后台操作，并校验样本源文件哈希及修改时间未变。

游戏资源不随程序或源码分发，需要用户提供自己的本地游戏安装目录。游戏资源的图片和名称归原权利人所有。

依赖参考：[Qt for Python](https://doc.qt.io/qtforpython-6/)、[UnityPy](https://github.com/K0lb3/UnityPy)、[YooAsset](https://github.com/tuyoogame/YooAsset)。这些依赖的许可证随发布目录提供；PySide6 / Qt 使用 LGPL 许可。
