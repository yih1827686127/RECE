const LANGUAGE_KEY = 'celeris-webgpu-language';
const SUPPORTED_LANGUAGES = new Set(['en', 'cn']);

let currentLanguage = normalizeLanguage(readStoredLanguage());
let observer = null;
let isApplyingLanguage = false;

const originalTextNodes = new WeakMap();
const originalAttributes = new WeakMap();

const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEXTAREA']);
const TRANSLATABLE_ATTRIBUTES = ['title', 'placeholder', 'aria-label', 'alt'];

const MESSAGES = {
  'language.label': { en: 'Language', cn: '语言' },
  'language.en': { en: 'EN', cn: 'EN' },
  'language.cn': { en: 'CN', cn: 'CN' },
  'alert.requiredFiles': {
    en: 'Please upload all the required files.',
    cn: '请上传所有必需文件。'
  },
  'error.webgpuUnsupported': {
    en: 'WebGPU is not supported in this browser.',
    cn: '此浏览器不支持 WebGPU。'
  },
  'chart.location': { en: 'Location {index}', cn: '位置 {index}' },
  'chart.time': { en: 'Time (s)', cn: '时间 (s)' },
  'chart.elevation': { en: 'Elevation (m)', cn: '高程 (m)' },
  'fullscreen.exit': { en: 'Exit Full Screen', cn: '退出全屏' },
  'disabled.reef3dMode': {
    en: 'This Celeris-WebGPU solver control is locked while REEF3D backend mode is selected. Change REEF3D parameters in the REEF3D runner and submit a new backend job.',
    cn: '当前已选择 REEF3D 后端模式，此 Celeris-WebGPU 求解器控件已锁定。请在 REEF3D 运行面板中修改参数并重新提交后端作业。'
  },
  'rece.workflow.starting': { en: 'Starting RECE workflow...', cn: '正在启动 RECE 工作流...' },
  'rece.workflow.status': { en: 'RECE workflow: {status}', cn: 'RECE 工作流：{status}' },
  'rece.workflow.complete': { en: 'RECE workflow complete. Run the RECE Hong Kong example.', cn: 'RECE 工作流已完成。请运行 RECE 香港示例。' },
  'rece.workflow.failed': { en: 'RECE workflow failed: {error}', cn: 'RECE 工作流失败：{error}' },
  'rece.workflow.error': { en: 'RECE workflow error: {error}', cn: 'RECE 工作流错误：{error}' },
  'rece.runner.selectReef3d': { en: 'Select REEF3D backend job to use this runner.', cn: '请选择 REEF3D 后端作业后再使用此运行器。' },
  'rece.runner.loadZip': { en: 'Load a REEF3D case zip before starting.', cn: '开始前请先加载 REEF3D case zip。' },
  'rece.runner.loadCeleris': { en: 'Load Celeris config.json and bathy.txt before starting REEF3D.', cn: '开始 REEF3D 前请先加载 Celeris config.json 和 bathy.txt。' },
  'rece.runner.submitting': { en: 'Submitting REEF3D job...', cn: '正在提交 REEF3D 作业...' },
  'rece.runner.queued': { en: 'REEF3D job queued: {id}', cn: 'REEF3D 作业已排队：{id}' },
  'rece.runner.status': { en: 'REEF3D {status}: {phase}; frames {frameCount}', cn: 'REEF3D {status}：{phase}；帧数 {frameCount}' },
  'rece.runner.live': { en: 'REEF3D live playback started; frames {frameCount}', cn: 'REEF3D 实时回放已开始；帧数 {frameCount}' },
  'rece.runner.complete': { en: 'REEF3D complete; frames {frameCount}', cn: 'REEF3D 已完成；帧数 {frameCount}' },
  'rece.runner.failed': { en: 'REEF3D failed: {error}', cn: 'REEF3D 失败：{error}' },
  'rece.runner.cancelled': { en: 'REEF3D job cancelled.', cn: 'REEF3D 作业已取消。' },
  'rece.runner.statusError': { en: 'REEF3D status error: {error}', cn: 'REEF3D 状态错误：{error}' },
  'rece.runner.cancelling': { en: 'Cancelling REEF3D job...', cn: '正在取消 REEF3D 作业...' },
  'rece.runner.cancelStatus': { en: 'REEF3D {status}: {phase}', cn: 'REEF3D {status}：{phase}' },
  'rece.runner.cancelError': { en: 'Cancel error: {error}', cn: '取消错误：{error}' },
  'rece.runner.startError': { en: 'REEF3D start error: {error}', cn: 'REEF3D 启动错误：{error}' },
};

const EXACT_CN = {
  'Celeris-WebGPU': 'Celeris-WebGPU',
  'Celeris-WebGPU: Transect Mode': 'Celeris-WebGPU：断面模式',
  'Start Here: Load Simulation Datafiles': '从这里开始：加载模拟数据文件',
  'Questions/Problems/Requests': '问题 / 故障 / 需求',
  '- use the': '- 请使用',
  'Users Forum': '用户论坛',
  'NOTE:': '注意：',
  'Options with an asterisk* are not currently working - these are largely placeholders for future updates.': '带星号 * 的选项目前尚不可用，主要是为未来更新预留的占位功能。',
  'Download Example Configurations': '下载示例配置',
  'here': '这里',
  'Upload Custom Configuration Files here:': '在此上传自定义配置文件：',
  'Load JSON Config File [Required]': '加载 JSON 配置文件 [必需]',
  'Load Bathymetry Data File [Required]': '加载水深/地形数据文件 [必需]',
  'Load Wave [amp,period,dir] Data File [Optional]': '加载波浪 [振幅, 周期, 方向] 数据文件 [可选]',
  'Load Initial Free Surface Data File [Optional]': '加载初始自由表面数据文件 [可选]',
  'Load Friction Map Data File [Optional]': '加载摩擦系数图数据文件 [可选]',
  'Load Hard (non-erodible) Bottom Elevation Data File [Optional]': '加载硬质（不可侵蚀）底床高程数据文件 [可选]',
  'For image overlay, you have two choices. If you have a high-resolution satellite or aerial image, you can load that file below. Note that this image must cover the exact area as the loaded bathy/topo, or the overlay will not be spatially matched. Alternatively, if you know the lat/lon coordinates of the corners of the bathy/topo, you can specify these in the input json file (see examples). Based on these corner coordinates, the code will download a Google Maps tile for the domain, and use that as an overlay.': '图像叠加有两种方式。如果你有高分辨率卫星图或航拍图，可以在下方加载该文件。注意，该图像必须覆盖与已加载水深/地形完全相同的区域，否则叠加图不会在空间上匹配。或者，如果你知道水深/地形四角的经纬度坐标，可以在输入 JSON 文件中指定这些坐标（见示例）。代码会根据这些角点坐标下载该区域的 Google Maps 瓦片并用作叠加图。',
  'Load Overlay Image (jpg, png, bmp, gif) [Optional]': '加载叠加图像 (jpg, png, bmp, gif) [可选]',
  'Experimental feature: To add 3D models to the "Explorer" view, upload a model json file. Details on the format of this file can be found': '实验性功能：若要向“Explorer”视图添加 3D 模型，请上传模型 JSON 文件。该文件格式的详细说明可见',
  'Load JSON 3D Model File [Optional]': '加载 JSON 3D 模型文件 [可选]',
  'Start Simulation': '开始模拟',
  'Run RECE REEF3D Workflow': '运行 RECE REEF3D 工作流',
  'Solver Mode': '求解器模式',
  'Celeris-WebGPU in browser': '浏览器内 Celeris-WebGPU',
  'REEF3D backend job': 'REEF3D 后端作业',
  'REEF3D Input': 'REEF3D 输入',
  'Use uploaded Celeris config/bathy/waves': '使用上传的 Celeris 配置 / 水深 / 波浪文件',
  'Use native REEF3D case zip': '使用原生 REEF3D case zip',
  'Load REEF3D Case ZIP [geo.dat, control.txt, ctrl.txt]': '加载 REEF3D Case ZIP [geo.dat, control.txt, ctrl.txt]',
  'MPI ranks': 'MPI 进程数',
  'Output frames': '输出帧数',
  'Wave height (m)': '波高 (m)',
  'Wave period (s)': '波周期 (s)',
  'Wave direction': '波向',
  'Output interval (s)': '输出间隔 (s)',
  'Advanced DiveMESH control.txt override': '高级 DiveMESH control.txt 覆盖',
  'Advanced REEF3D ctrl.txt override': '高级 REEF3D ctrl.txt 覆盖',
  'Run Custom REEF3D Job': '运行自定义 REEF3D 作业',
  'Cancel REEF3D Job': '取消 REEF3D 作业',
  'RECE Hong Kong smoke (REEF3D external frames)': 'RECE 香港烟测（REEF3D 外部帧）',
  'or, Load Pre-configured Examples here:': '或者，在此加载预配置示例：',
  'Choose Example:': '选择示例：',
  'Run Example Simulation': '运行示例模拟',
  'Pause / Resume Simulation:': '暂停 / 恢复模拟：',
  'Pause': '暂停',
  'Resume': '恢复',
  'Clear Memory / Reset Simulator': '清空内存 / 重置模拟器',
  'Modify Visualization': '修改可视化',
  'Property to Plot:': '绘制属性：',
  'Free Surface Elevation (m)': '自由表面高程 (m)',
  'Water Surface Elevation (m)': '水面高程 (m)',
  'Bathymetry/Topography (m)': '水深/地形 (m)',
  'Topography (m)': '地形 (m)',
  'Bottom Friction Map': '底床摩擦图',
  'Fluid Speed (m/s)': '流速大小 (m/s)',
  'East-West (x) Velocity (m/s)': '东西向 (x) 速度 (m/s)',
  'North-South (y) Velocity (m/s)': '南北向 (y) 速度 (m/s)',
  'Vertical Vorticity (1/s)': '垂向涡度 (1/s)',
  'Total Vertical Vorticity (m/s)': '总垂向涡度 (m/s)',
  'Mean |Vertical Vorticity| (1/s)': '平均 |垂向涡度| (1/s)',
  'Foam / Tracer Concentration': '泡沫 / 示踪物浓度',
  'Mean Foam / Tracer Concentration': '平均泡沫 / 示踪物浓度',
  'Max Free Surface Elev (m)': '最大自由表面高程 (m)',
  'Mean Free Surface Elev (m)': '平均自由表面高程 (m)',
  'Mean Fluid Speed [Magn] (m/s)': '平均流速大小 [Magn] (m/s)',
  'Mean Fluid Speed [E-W] (m/s)': '平均东西向流速 [E-W] (m/s)',
  'Mean Fluid Speed [N-S] (m/s)': '平均南北向流速 [N-S] (m/s)',
  'Mean Fluid Flux [Magn] (m^2/s)': '平均流量通量大小 [Magn] (m^2/s)',
  'Mean Fluid Flux [E-W] (m^2/s)': '平均东西向流量通量 [E-W] (m^2/s)',
  'Mean Fluid Flux [N-S] (m^2/s)': '平均南北向流量通量 [N-S] (m^2/s)',
  'RMS Wave Height (m)': '均方根波高 (RMS, m)',
  'Significant Wave Height (m)': '显著波高 (Hs, m)',
  'Difference from Baseline Hs (m)': '相对基准显著波高 Hs 的差值 (m)',
  'Depth Change due to Sed Transport': '泥沙输运导致的水深变化',
  'Sediment Class 1 Concentration': '泥沙类别 1 浓度',
  'Sediment Class 1 Erosion Rate': '泥沙类别 1 侵蚀速率',
  'Sediment Class 1 Available Depth': '泥沙类别 1 可用厚度',
  'Design Component Map': '设计构件图',
  'Colorbar Choices:': '色标选择：',
  'Ocean': '海洋',
  'Parula': 'Parula',
  'Turbo': 'Turbo',
  'HSV': 'HSV',
  'Gray': '灰度',
  'Pink': '粉色',
  'Bathy/Topo': '水深/地形',
  'Water / Photorealistic': '水面 / 写实',
  'Topo': '地形',
  'Maximum Color Axis Value (in units of plotted property):': '颜色轴最大值（单位同绘制属性）：',
  'Minimum Color Axis Value (in units of plotted property):': '颜色轴最小值（单位同绘制属性）：',
  'Update': '更新',
  'Transport Overlays:': '输运叠加层：',
  'Show Areas of Foam': '显示泡沫区域',
  'No Foam or Tracer': '不显示泡沫或示踪物',
  'Passive Tracer Conc': '被动示踪物浓度',
  'Google Maps / Aerial Image Overlay:': 'Google Maps / 航拍图像叠加：',
  'No Overlay': '无叠加图',
  'Include Google Maps Overlay': '包含 Google Maps 叠加图',
  'Include Satellite / Aerial Overlay': '包含卫星 / 航拍叠加图',
  'Show flow field vector arrows:': '显示流场矢量箭头：',
  'No': '否',
  'Yes': '是',
  'Instantaneous Velocity Vectors': '瞬时速度矢量',
  'Time-Averaged Velocity Vectors': '时间平均速度矢量',
  'Arrow scale factor:': '箭头缩放系数：',
  'Arrow density factor:': '箭头密度系数：',
  'Show USACE & USC logos:': '显示 USACE 与 USC 标志：',
  'Show USC logos:': '显示 USC 标志：',
  'View Mode:': '视图模式：',
  '-Design: 2D view, modify surfaces': '-Design：2D 视图，修改表面',
  '-Explorer: 3D view, fly-trough scene': '-Explorer：3D 视图，飞行浏览场景',
  'Design - 2D view, modify surfaces': 'Design - 2D 视图，修改表面',
  'Explorer - 3D view, fly-trough scene': 'Explorer - 3D 视图，飞行浏览场景',
  'View Simulation in Full Screen': '全屏查看模拟',
  'Exit Full Screen': '退出全屏',
  'Add Engineered Design Components': '添加工程设计构件',
  'Component to Add:': '要添加的构件：',
  'Coral Reef': '珊瑚礁',
  'Mussel/Oyster Bed': '贻贝/牡蛎床',
  'Mangroves': '红树林',
  'Kelp Bed': '海带床',
  'Light Vegetation (grass)': '轻型植被（草地）',
  'Medium Vegetation (shrub/scrub)': '中型植被（灌木/低矮植被）',
  'Rubblemound Structure': '抛石堆结构',
  'Vegetated Dune': '植被沙丘',
  'Berm / Temporary Dune': '护坡平台 / 临时沙丘',
  'Seawall': '海堤',
  'Smooth Concrete Channel': '光滑混凝土河道',
  'Soil / Muddy Channel': '土质 / 泥质河道',
  'Trees': '树木',
  'Desert / Sand Vegetation': '荒漠 / 沙地植被',
  'Stone Revetment': '块石护坡',
  'Sand': '沙地',
  'Soil': '土壤',
  'Mannings n / Friction Factors': 'Manning n / 摩擦系数',
  'Coral Reef:': '珊瑚礁：',
  'Mussel/Oyster Bed:': '贻贝/牡蛎床：',
  'Mangroves:': '红树林：',
  'Kelp Bed:': '海带床：',
  'Grass:': '草地：',
  'Scrub:': '灌木：',
  'Rubblemound:': '抛石堆：',
  'Vegetated Dune:': '植被沙丘：',
  'Berm:': '护坡平台：',
  'Seawall:': '海堤：',
  'Smooth Concrete Channel:': '光滑混凝土河道：',
  'Soil / Muddy Channel:': '土质 / 泥质河道：',
  'Trees:': '树木：',
  'Sandy Vegetation:': '沙地植被：',
  'Stone Revetment:': '块石护坡：',
  'Sandy Surface:': '沙质表面：',
  'Soil Surface:': '土质表面：',
  'For surface cover components, radius of coverage to add on click:': '对于面状覆盖构件，点击添加时的覆盖半径：',
  'Left click (and hold) to add surface cover components (in Design Mode).': '左键点击（并按住）以添加面状覆盖构件（Design 模式）。',
  '*For linear structures (breakwaters, dunes, seawalls), crest elevation (m):': '*线性结构（防波堤、沙丘、海堤）的堤顶高程 (m)：',
  '*For linear structures (breakwaters, dunes, seawalls), crest width (m):': '*线性结构（防波堤、沙丘、海堤）的堤顶宽度 (m)：',
  '*For linear, sloping structures (breakwaters, dunes), side slope (give as decimal, e.g. 0.25 = 1/4):': '*线性斜坡结构（防波堤、沙丘）的边坡坡度（用小数表示，例如 0.25 = 1/4）：',
  '*Choose Linear Structure Start/Endpoint Coordinate to Edit:': '*选择要编辑的线性结构起点/终点坐标：',
  'Start Location': '起点位置',
  'End Location': '终点位置',
  '*Right-click on structure start/end location (in Design Mode) or input coordinates below': '*右键点击结构起点/终点位置（Design 模式），或在下方输入坐标',
  'Location x-coordinate (m) :': '位置 x 坐标 (m)：',
  'Location y-coordinate (m) :': '位置 y 坐标 (m)：',
  'Add Linear Structure': '添加线性结构',
  'Modify Sea Level & Edit Bathy/Topo': '修改海平面并编辑水深/地形',
  'Edit Channel & Topography': '编辑河道与地形',
  'Change in stil water level (m of surge, tide, SLR):': '静水位变化（风暴潮、潮汐、海平面上升 SLR，m）：',
  'Property to Edit:': '要编辑的属性：',
  'Bottom Friction': '底床摩擦',
  'Passive Tracer Sources': '被动示踪物源',
  'Passive Pollutant Sources': '被动污染物源',
  'Ocean Surface Elevation': '海面高程',
  'Ground / Channel Elevation': '地面 / 河道高程',
  'Water Surface Elevation': '水面高程',
  'Change Property Continuously or Set to Specific Value:': '连续改变属性或设为指定值：',
  'Increase/Decrease on Click': '点击时增加/减少',
  'Set to Value on Click': '点击时设为指定值',
  'Amount of Property to Change-on-Click / Value to Set on Click:': '点击时属性变化量 / 点击时设置值：',
  'Lengthscale (m) of Change-on-Click :': '点击改变的长度尺度 (m)：',
  'Modify Boundary Conditions': '修改边界条件',
  'Change River Flow': '改变河道流量',
  'Choose Design Flood to Simulate:': '选择要模拟的设计洪水：',
  '10-yr Flood': '10 年一遇洪水',
  '50-yr Flood': '50 年一遇洪水',
  '100-yr Flood': '100 年一遇洪水',
  '200-yr Flood': '200 年一遇洪水',
  '500-yr Flood': '500 年一遇洪水',
  'Upstream (left) River Elevation (m):': '上游（左侧）河流水位高程 (m)：',
  'Upstream (left) River Flow Speed (m/s):': '上游（左侧）河流流速 (m/s)：',
  'Incident Wave Type:': '入射波类型：',
  'Sine Wave (single harmonic)': '正弦波（单一谐波）',
  '*Sine Wave (single harmonic)': '*正弦波（单一谐波）',
  'TMA Spectrum': 'TMA 谱',
  '*TMA Spectrum': '*TMA 谱',
  '*Transient Pulse (4 waves)': '*瞬态脉冲（4 个波）',
  '*Solitary Wave': '*孤立波',
  'Custom Spectrum from loaded file': '使用已加载文件中的自定义谱',
  '*Time Series from loaded file': '*使用已加载文件中的时间序列',
  'Height (m) of Sine Wave / Pulse / Solitary Wave, or Significant Wave Height of Spectrum:': '正弦波 / 脉冲 / 孤立波高度 (m)，或谱的显著波高：',
  'Period (sec) of Sine Wave / Pulse, or Peak Period of Spectrum [not used for Solitary Wave]:': '正弦波 / 脉冲周期 (s)，或谱峰值周期 [孤立波不使用]：',
  'Wave Direction (deg, 0=from west, 90=from south, 180=from east, -90/270=from north):': '波向（度，0=自西向东，90=自南向北，180=自东向西，-90/270=自北向南）：',
  'Wave Direction (deg CCW from E [-180 to 180]):': '波向（从东向逆时针计，度，[-180, 180]）：',
  'West Boundary Type:': '西侧边界类型：',
  'East Boundary Type:': '东侧边界类型：',
  'South Boundary Type:': '南侧边界类型：',
  'North Boundary Type:': '北侧边界类型：',
  'Solid Wall': '固壁',
  'Sponge Layer': '海绵层',
  'Incident Waves': '入射波',
  '*Periodic Boundary': '*周期边界',
  'Configure Sediment Transport Model': '配置泥沙输运模型',
  'BETA - currently no feedback w/ hydro': 'BETA - 当前尚未与水动力反馈耦合',
  'Sediment Class 1 D50 (mm):': '泥沙类别 1 D50 (mm)：',
  'Sediment Class 1 porosity:': '泥沙类别 1 孔隙率：',
  'Sediment Class 1 specific gravity:': '泥沙类别 1 比重：',
  'Sediment Class 1 psi (erosion) parameter:': '泥沙类别 1 psi（侵蚀）参数：',
  'Sediment Class 1 psi parameter:': '泥沙类别 1 psi 参数：',
  'Sediment Class 1 critical Shields #:': '泥沙类别 1 临界 Shields 数：',
  'Turn on/off Sediment Transport Model:': '开启/关闭泥沙输运模型：',
  'No Sediment Transport': '不使用泥沙输运',
  'Include Sediment Transport': '包含泥沙输运',
  'Add Impulsive Wave Source (Earthquake, Landslide)': '添加脉冲波源（地震、滑坡）',
  'Wave Disturbance to Add:': '要添加的波浪扰动：',
  'Solitary Wave': '孤立波',
  '*Earthquake': '*地震',
  '*Submerged Landslide': '*水下滑坡',
  'Subaerial Landslide': '水上滑坡',
  'X-Coordinate of Source (m):': '源区 X 坐标 (m)：',
  'Y-Coordinate of Source (m):': '源区 Y 坐标 (m)：',
  'Crest Amplitude / Earthquake Slip / Max Slide Thickness (m):': '波峰振幅 / 地震滑移量 / 最大滑坡厚度 (m)：',
  'Direction / Orientation / Strike of Source (deg CCW from E [-180 to 180]):': '源方向 / 朝向 / 走向（从东向逆时针计，度，[-180, 180]）：',
  'Characteristic Width of Source (m, not used for Solitary Wave):': '源特征宽度 (m，孤立波不使用)：',
  'Characteristic Length of Source (m, not used for Solitary Wave):': '源特征长度 (m，孤立波不使用)：',
  'Rake of Source (deg, only used for Earthquake):': '源滑动角 Rake（度，仅地震使用）：',
  'Dip of Source (deg, only used for Earthquake):': '源倾角 Dip（度，仅地震使用）：',
  'Add Disturbance': '添加扰动',
  'Plot Time Series': '绘制时间序列',
  'Total Number of Time Series:': '时间序列总数：',
  'Duration of Time Series to Plot & Save (sec) :': '绘制并保存时间序列的持续时间 (s)：',
  "Model will save time series data once this duration is reached; a new data file will be generated every instance that the duration is reached (plot time reaches the duration). Data files will be located in your browser's default Downloads directory.": '达到该持续时间后，模型会保存时间序列数据；每次达到该持续时间（绘图时间达到持续时间）都会生成新的数据文件。数据文件将保存在浏览器默认下载目录中。',
  'Time Series Location to Update:': '要更新的时间序列位置：',
  'Right-click on time series location (in Design Mode) or input coordinates below': '右键点击时间序列位置（Design 模式），或在下方输入坐标',
  'New Time Series x-location (m) :': '新的时间序列 x 位置 (m)：',
  'New Time Series y-location (m) :': '新的时间序列 y 位置 (m)：',
  'Analysis and Statistics': '分析与统计',
  'Store Baseline Wave Height Surface in Memory': '将基准波高表面存入内存',
  'Reset Mean & Max Surfaces': '重置平均值与最大值表面',
  'Reset Wave Height Surface': '重置波高表面',
  'Outputs: Animations & Images': '输出：动画与图像',
  "Files saved below will be located in your browser's default Downloads directory": '下方保存的文件将位于浏览器默认下载目录',
  'Download Current Simulation Image (JPG)': '下载当前模拟图像 (JPG)',
  'For long duration movies, it is recommended to use various screen capture options, such as the "Snipping Tool" in Windows. Limitations of working within the browser / js environment make storing many frames and generating large animations challenging. The options below will allow the user to make short animated gifs (up to ~100 frames) and to save up to 256 jpeg images. Note that you can have only one of these operations ongoing at a time.': '对于长时程影片，建议使用各类屏幕录制工具，例如 Windows 的“截图工具”。浏览器 / JS 环境的限制会让存储大量帧并生成大型动画变得困难。下方选项允许用户生成短动画 GIF（最多约 100 帧）并保存最多 256 张 JPEG 图像。注意，同一时间只能进行其中一种操作。',
  'Animated gif Options:': '动画 GIF 选项：',
  'Time between frames (sec) :': '帧间时间 (s)：',
  'Click the button below to start the creation of the animation. See the console for messages about the progress of the file generation.': '点击下方按钮开始创建动画。请在控制台查看文件生成进度信息。',
  'Create Animated gif': '创建动画 GIF',
  'JPEG Time Stack Options:': 'JPEG 时间栈选项：',
  'Time between jpeg images (sec) :': 'JPEG 图像间隔时间 (s)：',
  'Number of images to save (max: 256) :': '要保存的图像数量（最大 256）：',
  'Click the button below to start the storage of the jpeg images in memory. Once all of the images are stored, they will be saved to file. See the console for progress messages.': '点击下方按钮开始将 JPEG 图像存入内存。所有图像存储完成后将保存为文件。请在控制台查看进度信息。',
  'Create JPEG stack': '创建 JPEG 栈',
  'Output: Raw Model Data': '输出：原始模型数据',
  'Download Simulation Parameters JSON file': '下载模拟参数 JSON 文件',
  'Write Single 2D Surface Options:': '写出单个 2D 表面选项：',
  'Property to Write to File:': '要写入文件的属性：',
  'X-Dir Fluid Flux [E-W] (m^2/s)': 'X 向流量通量 [E-W] (m^2/s)',
  'Y-Dir Fluid Flux [N-S] (m^2/s)': 'Y 向流量通量 [N-S] (m^2/s)',
  'Turbulent Eddy Viscosity (m^2/s)': '湍流涡黏性 (m^2/s)',
  'Download Single 2D Surface Data (binary)': '下载单个 2D 表面数据（二进制）',
  'Time Stacks of 2D Surface Data Write Options:': '2D 表面数据时间栈写出选项：',
  'Time interval to write surface data (sec) :': '写出表面数据的时间间隔 (s)：',
  'Write free surface elevation to file:': '将自由表面高程写入文件：',
  'Write x-direction flux (HU) to file:': '将 x 方向通量 (HU) 写入文件：',
  'Write y-direction flux (HV) to file:': '将 y 方向通量 (HV) 写入文件：',
  'Write turbulent (breaking and mixing) eddy viscosity to file:': '将湍流（破碎与混合）涡黏性写入文件：',
  'Click the button below to start the writing of 2D surface data to files. Data will be written in raw binary for surface data, and ASCII for time and coordinate data. You can use this': '点击下方按钮开始将 2D 表面数据写入文件。表面数据将以原始二进制格式写出，时间和坐标数据将以 ASCII 格式写出。你可以使用这个',
  'example Matlab script': '示例 Matlab 脚本',
  'to plot the data. Note that writing data to files will slow the simulation, and will tend to make the user interface sluggish; when writing data files frequently (>10 writes per wave period), no to minimal interaction with the simulation is recommended. See the console for progress messages.': '来绘制数据。注意，写出数据文件会减慢模拟，并可能让用户界面变得迟滞；当频繁写出数据文件（每个波周期写出超过 10 次）时，建议尽量少与模拟交互。请在控制台查看进度信息。',
  'Start Writing 2D Data to File': '开始写出 2D 数据到文件',
  'Stop Writing 2D Data to File': '停止写出 2D 数据到文件',
  'Modify Simulation Parameters': '修改模拟参数',
  'Simulation Type:': '模拟类型：',
  'NLSW': 'NLSW',
  'Boussinesq': 'Boussinesq',
  'Theta value for MinMod, ranges from 1.0 (most dissipative, upwind differences) to 2.0 (least dissipative, centered differences) [default: 2.0 w/ breaking model]:': 'MinMod 的 Theta 值，范围从 1.0（耗散最强，上风差分）到 2.0（耗散最弱，中心差分）[默认：2.0，启用破碎模型]：',
  'Change Courant Number (0.1 or less for Explicit Scheme, 0.2 or less for Implicit Scheme):': '修改 Courant 数（显式格式建议不超过 0.1，隐式格式建议不超过 0.2）：',
  'Bottom Friction Model:': '底床摩擦模型：',
  'Quadratic Friction Drag': '二次摩擦阻力',
  'Mannings Equation': 'Manning 公式',
  'Change Mannings n (typical value ~0.025) or Friction Factor (typical value ~0.002):': '修改 Manning n（典型值约 0.025）或摩擦系数（典型值约 0.002）：',
  'Wave Breaking Model:': '波浪破碎模型：',
  'Breaking Eddy Viscosity Model': '破碎涡黏性模型',
  'None; numerical dissipation only': '无；仅使用数值耗散',
  'Threshold to Start Wave Breaking [Default: 0.5]:': '开始波浪破碎的阈值 [默认：0.5]：',
  'Threshold to End Wave Breaking [Default: 0.15]:': '结束波浪破碎的阈值 [默认：0.15]：',
  'Breaking Transition Time Coefficient [Default: 5.0]:': '破碎过渡时间系数 [默认：5.0]：',
  'Breaking Eddy Viscosity Coefficient [Default: 2.0]:': '破碎涡黏性系数 [默认：2.0]：',
  'Turbulent Dispersion ([m^2/s]; for foam/scalar transport):': '湍流扩散 ([m^2/s]；用于泡沫/标量输运)：',
  'Turbulence Decay Rate (1st Order Decay [1/s]; for foam/scalar transport):': '湍流衰减率（一阶衰减 [1/s]；用于泡沫/标量输运）：',
  'Dry Beach Infiltration Rate [m/s; Default: 0.001]]:': '干滩入渗率 [m/s；默认：0.001]：',
  'Time Steps Between each Render Frame (1 or greater, 0 for auto-determine for max sim speed):': '每个渲染帧之间的时间步数（1 或更大；0 表示自动决定以获得最大模拟速度）：',
  'Copyright Patrick Lynett 2024': '版权所有 Patrick Lynett 2024',
  'Copyright Patrick Lynett 2024, 2025': '版权所有 Patrick Lynett 2024, 2025',
  'Developed with support from USACE ERDC, ONR, and the NSF': '在 USACE ERDC、ONR 和 NSF 支持下开发',
  'Simulation Window': '模拟窗口',
  'Time Series Plots': '时间序列图',
  'Simulation Parameters': '模拟参数',
  'Simulation Console': '模拟控制台',
  '--- Simulation Parameters ---': '--- 模拟参数 ---',
  '--- Runtime Parameters ---': '--- 运行时参数 ---',
  'NLSW Simulation': 'NLSW 模拟',
  'River Simulation': '河道模拟',
  'Boussinesq Simulation': 'Boussinesq 模拟',
  'High-Order Boussinesq Simulation': '高阶 Boussinesq 模拟',
  '4th-Order Implicit Predictor-Corrector Scheme': '四阶隐式预测-校正格式',
  '3rd-Order Explicit Predictor Scheme': '三阶显式预测格式',
  'Usings Mannings Friction Law': '使用 Manning 摩擦律',
  'Usings Quadratic Friction Law': '使用二次摩擦律',
  'Simulation Completed': '模拟完成',
  'Please upload all the required files.': '请上传所有必需文件。',
  'WebGPU is not supported in this browser.': '此浏览器不支持 WebGPU。',
};

const PHRASE_REPLACEMENTS = [
  [/Celeris-WebGPU v\.2025\.03\.04 \[River Version\]/g, 'Celeris-WebGPU v.2025.03.04 [河道版本]'],
  [/Celeris-WebGPU v\.2025\.01\.21/g, 'Celeris-WebGPU v.2025.01.21'],
  [/, wind waves/g, '，风浪'],
  [/, tsunami/g, '，海啸'],
  [/, tides/g, '，潮汐'],
  [/, hot start/g, '，热启动'],
  [/, High-Order mode/g, '，高阶模式'],
  [/, normal/g, '，法向入射'],
  [/, NE/g, '，东北向'],
  [/, SW/g, '，西南向'],
  [/Directional Wave Basin/g, '定向波浪水槽'],
  [/Seaside Experiments/g, 'Seaside 实验'],
  [/Toy Problem/g, '玩具问题'],
  [/LA River Large/g, 'LA River 大型模型'],
  [/Glendale Narrows/g, 'Glendale Narrows'],
  [/Grid Size in X-direction \(m\):/g, 'X 方向网格尺寸 (m)：'],
  [/Grid Size in Y-direction \(m\):/g, 'Y 方向网格尺寸 (m)：'],
  [/Cells in X-direction:/g, 'X 方向网格单元数：'],
  [/Cells in Y-direction:/g, 'Y 方向网格单元数：'],
  [/Courant Number:/g, 'Courant 数：'],
  [/Time Step \(s\):/g, '时间步长 (s)：'],
  [/Base \(deep-water\) Depth \(m\):/g, '基准（深水）水深 (m)：'],
  [/Wave Breaking Slope Threshold:/g, '波浪破碎坡度阈值：'],
  [/Turbulent Decay Coefficient:/g, '湍流衰减系数：'],
  [/Simulated Time \(min\) Since Config Change:/g, '配置变化后的模拟时间 (min)：'],
  [/Simulated Time \(min\):/g, '模拟时间 (min)：'],
  [/Faster-than-Realtime Ratio:/g, '快于实时倍率：'],
  [/Render Frame Interval:/g, '渲染帧间隔：'],
  [/West Boundary: Unknown/g, '西侧边界：未知'],
  [/East Boundary: Unknown/g, '东侧边界：未知'],
  [/South Boundary: Unknown/g, '南侧边界：未知'],
  [/North Boundary: Unknown/g, '北侧边界：未知'],
  [/West Boundary: Solid Wall/g, '西侧边界：固壁'],
  [/East Boundary: Solid Wall/g, '东侧边界：固壁'],
  [/South Boundary: Solid Wall/g, '南侧边界：固壁'],
  [/North Boundary: Solid Wall/g, '北侧边界：固壁'],
  [/West Boundary: Sponge Layer/g, '西侧边界：海绵层'],
  [/East Boundary: Sponge Layer/g, '东侧边界：海绵层'],
  [/South Boundary: Sponge Layer/g, '南侧边界：海绵层'],
  [/North Boundary: Sponge Layer/g, '北侧边界：海绵层'],
  [/West Boundary: Incoming Wave/g, '西侧边界：入射波'],
  [/East Boundary: Incoming Wave/g, '东侧边界：入射波'],
  [/South Boundary: Incoming Wave/g, '南侧边界：入射波'],
  [/North Boundary: Incoming Wave/g, '北侧边界：入射波'],
  [/West Boundary: Periodic Boundary/g, '西侧边界：周期边界'],
  [/East Boundary: Periodic Boundary/g, '东侧边界：周期边界'],
  [/South Boundary: Periodic Boundary/g, '南侧边界：周期边界'],
  [/North Boundary: Periodic Boundary/g, '北侧边界：周期边界'],
  [/Location ([0-9]+)/g, '位置 $1'],
  [/X:/g, 'X：'],
  [/Y:/g, 'Y：'],
  [/x-coordinate \(m\):/g, 'x 坐标 (m)：'],
  [/y-coordinate \(m\):/g, 'y 坐标 (m)：'],
  [/bottom elevation \(m\):/g, '底床高程 (m)：'],
  [/bathy\/topo \(m\):/g, '水深/地形 (m)：'],
  [/friction factor:/g, '摩擦系数：'],
  [/surface elevation \(m\):/g, '自由表面高程 (m)：'],
  [/flow depth \(m\):/g, '流深 (m)：'],
  [/flow speed \(m\/s\):/g, '流速 (m/s)：'],
  [/max free surface \(m\):/g, '最大自由表面 (m)：'],
  [/sig wave height \(m\):/g, '显著波高 (m)：'],
  [/Starting Celeris-WebGPU/g, '启动 Celeris-WebGPU'],
  [/Clearing \/ destroying any data from previous run\.\.\./g, '正在清除 / 销毁上一次运行的数据...'],
  [/Failed to find a high-performance GPU adapter, using available GPU\./g, '未找到高性能 GPU 适配器，改用可用 GPU。'],
  [/Found high-performance GPU adapter\./g, '已找到高性能 GPU 适配器。'],
  [/GPU Device acquired, starting resource creation\.\.\./g, '已获取 GPU 设备，开始创建资源...'],
  [/Creating 2D textures\.\.\./g, '正在创建 2D 纹理...'],
  [/Downloading surface texture images\.\.\./g, '正在下载表面纹理图像...'],
  [/Downloading skybox images\.\.\./g, '正在下载天空盒图像...'],
  [/Shaders loaded\./g, '着色器已加载。'],
  [/Pipelines set up\./g, '管线已设置。'],
  [/Buffers set up\./g, '缓冲区已设置。'],
  [/Compute \/ Render loop starting\./g, '计算 / 渲染循环开始。'],
  [/Simulation parameters set\./g, '模拟参数已设置。'],
  [/Config loaded successfully from the uploaded file\./g, '已从上传文件成功加载配置。'],
  [/Server side example config\.json loaded successfully\./g, '已成功加载服务器端示例 config.json。'],
  [/Loading server side config\.json file/g, '正在加载服务器端 config.json 文件'],
  [/Bathy data loaded successfully from the uploaded file\./g, '已从上传文件成功加载水深数据。'],
  [/Loading server side example bathytopo file/g, '正在加载服务器端示例水深/地形文件'],
  [/Server side bathytopo data loaded successfully\./g, '已成功加载服务器端水深/地形数据。'],
  [/Bathytopo data parsed successfully\./g, '水深/地形数据解析成功。'],
  [/Initial Condition data loaded successfully from the uploaded file\./g, '已从上传文件成功加载初始条件数据。'],
  [/Friction data loaded successfully from the uploaded file\./g, '已从上传文件成功加载摩擦数据。'],
  [/Hard Bottom data loaded successfully from the uploaded file\./g, '已从上传文件成功加载硬质底床数据。'],
  [/Waves data loaded successfully from the uploaded file\./g, '已从上传文件成功加载波浪数据。'],
  [/Wave data parsed successfully\./g, '波浪数据解析成功。'],
  [/Looking for server side overlay file\.\.\./g, '正在查找服务器端叠加图文件...'],
  [/No Overlay file found/g, '未找到叠加图文件'],
  [/Server side overlay file loaded successfully\./g, '已成功加载服务器端叠加图文件。'],
  [/Loading Uploaded Overlay File/g, '正在加载上传的叠加图文件'],
  [/Custom overlay image loaded, dimensions:/g, '自定义叠加图像已加载，尺寸：'],
  [/Updating Overlay with Google Maps Image/g, '正在使用 Google Maps 图像更新叠加图'],
  [/Updating Overlay with Sat Image/g, '正在使用卫星图像更新叠加图'],
  [/Updating Design Components/g, '正在更新设计构件'],
  [/Trigger write - Creating animation of the simulation/g, '触发写出 - 正在创建模拟动画'],
  [/Setting screen render rate to match image frame rate/g, '正在设置屏幕渲染速率以匹配图像帧率'],
  [/Creating 3D Texture for Image Stack/g, '正在为图像栈创建 3D 纹理'],
  [/Storing image frame #/g, '正在存储图像帧 #'],
  [/Reading frame #/g, '正在读取帧 #'],
  [/into animated gif/g, '到动画 GIF'],
  [/Animated gif Complete - sending to write buffer\.  May take up to 60 seconds to save\./g, '动画 GIF 完成 - 正在发送到写入缓冲区。保存可能最多需要 60 秒。'],
  [/Trigger write - Reseting mean surfaces/g, '触发写出 - 正在重置平均表面'],
  [/Trigger write - Reseting wave height surfaces/g, '触发写出 - 正在重置波高表面'],
  [/Trigger write - Writing wave height and other surfaces to file/g, '触发写出 - 正在将波高及其他表面写入文件'],
  [/Trigger write - Start 2D surface data to file/g, '触发写出 - 开始将 2D 表面数据写入文件'],
  [/Trigger write - Stop 2D surface data to file/g, '触发写出 - 停止将 2D 表面数据写入文件'],
  [/Writing 2D surface data to file at time \(s\)/g, '正在时间 (s) 写出 2D 表面数据'],
  [/with increment\(s\)/g, '写出间隔 (s)'],
  [/Entered full screen mode/g, '已进入全屏模式'],
  [/Exited full screen mode/g, '已退出全屏模式'],
  [/Entered pseudo-fullscreen mode/g, '已进入伪全屏模式'],
  [/Exited pseudo-fullscreen mode/g, '已退出伪全屏模式'],
  [/Changing calc_constants\.whichPanelisOpen to/g, '正在将 calc_constants.whichPanelisOpen 改为'],
  [/Updating ([A-Za-z0-9_]+) with value:/g, '正在用数值更新 $1：'],
];

function normalizeLanguage(lang) {
  return SUPPORTED_LANGUAGES.has(lang) ? lang : 'en';
}

function readStoredLanguage() {
  try {
    return localStorage.getItem(LANGUAGE_KEY) || 'en';
  } catch {
    return 'en';
  }
}

function writeStoredLanguage(lang) {
  try {
    localStorage.setItem(LANGUAGE_KEY, lang);
  } catch {
    // Ignore storage failures; language switching still works for the current page.
  }
}

export function getLanguage() {
  return currentLanguage;
}

export function t(key, params = {}) {
  const message = MESSAGES[key]?.[currentLanguage] ?? MESSAGES[key]?.en ?? key;
  return message.replace(/\{([^}]+)\}/g, (_, name) => {
    return params[name] ?? '';
  });
}

export function translateText(value, lang = currentLanguage) {
  if (lang !== 'cn' || typeof value !== 'string') {
    return value;
  }

  const leading = value.match(/^\s*/)?.[0] ?? '';
  const trailing = value.match(/\s*$/)?.[0] ?? '';
  const compact = value.trim().replace(/\s+/g, ' ');
  if (!compact) {
    return value;
  }

  let translated = EXACT_CN[compact] ?? compact;
  for (const [pattern, replacement] of PHRASE_REPLACEMENTS) {
    translated = translated.replace(pattern, replacement);
  }
  return `${leading}${translated}${trailing}`;
}

export function applyLanguage(lang, options = {}) {
  const nextLanguage = normalizeLanguage(lang);
  currentLanguage = nextLanguage;
  if (options.persist !== false) {
    writeStoredLanguage(nextLanguage);
  }

  isApplyingLanguage = true;
  disconnectObserver();
  document.documentElement.lang = nextLanguage === 'cn' ? 'zh-CN' : 'en';
  translateNode(document.body);
  translateDocumentTitle();
  updateToggleState();
  reconnectObserver();
  isApplyingLanguage = false;

  document.dispatchEvent(new CustomEvent('celeris-language-change', {
    detail: { language: currentLanguage }
  }));
}

export function initLanguageToggle() {
  if (document.readyState === 'loading' && !document.getElementById('horizontalbar')) {
    document.addEventListener('DOMContentLoaded', initLanguageToggle, { once: true });
    return;
  }

  installStyles();
  installToggle();
  startObserver();
  applyLanguage(currentLanguage, { persist: false });
}

function installStyles() {
  if (document.getElementById('celeris-i18n-style')) {
    return;
  }
  const style = document.createElement('style');
  style.id = 'celeris-i18n-style';
  style.textContent = `
    .language-toggle {
      border: 1px solid rgba(255, 255, 255, 0.09);
      background: rgba(255, 255, 255, 0.035);
      border-radius: 8px;
      margin: 0 0 12px;
      padding: 10px 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      color: #cfc8bd;
      font-family: "Segoe UI", "Microsoft YaHei UI", Arial, sans-serif;
      font-size: 13px;
    }
    .language-toggle__buttons {
      display: inline-flex;
      gap: 6px;
    }
    .language-toggle__button {
      border: 1px solid rgba(255, 255, 255, 0.18);
      border-radius: 6px;
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.09), rgba(255, 255, 255, 0.025));
      color: #f0ede7;
      cursor: pointer;
      padding: 4px 10px;
      min-width: 40px;
      min-height: 30px;
      font-family: "Cascadia Mono", Consolas, monospace;
    }
    .language-toggle__button:last-child {
      border-right: 1px solid rgba(255, 255, 255, 0.18);
    }
    .language-toggle__button.is-active {
      background: rgba(255, 81, 63, 0.18);
      border-color: #ff513f;
      color: #fff;
    }
  `;
  document.head.appendChild(style);
}

function installToggle() {
  const existingToggle = document.getElementById('language-toggle');
  if (existingToggle) {
    bindToggle(existingToggle);
    return;
  }

  const host = document.getElementById('horizontalbar') || document.body;
  const toggle = document.createElement('div');
  toggle.id = 'language-toggle';
  toggle.className = 'language-toggle';
  toggle.setAttribute('data-i18n-skip', 'true');
  toggle.innerHTML = `
    <span class="language-toggle__label">${MESSAGES['language.label'].en}</span>
    <span class="language-toggle__buttons" role="group" aria-label="${MESSAGES['language.label'].en}">
      <button type="button" class="language-toggle__button" data-lang="en">EN</button>
      <button type="button" class="language-toggle__button" data-lang="cn">CN</button>
    </span>
  `;

  bindToggle(toggle);

  host.insertBefore(toggle, host.firstElementChild);
}

function bindToggle(toggle) {
  if (toggle.dataset.i18nBound === 'true') {
    return;
  }

  toggle.querySelectorAll('[data-lang]').forEach((button) => {
    button.addEventListener('click', () => applyLanguage(button.dataset.lang));
  });
  toggle.dataset.i18nBound = 'true';
}

function updateToggleState() {
  const toggle = document.getElementById('language-toggle');
  if (!toggle) {
    return;
  }
  const label = toggle.querySelector('.language-toggle__label');
  if (label) {
    label.textContent = MESSAGES['language.label'][currentLanguage];
  }
  toggle.querySelectorAll('[data-lang]').forEach((button) => {
    const active = button.dataset.lang === currentLanguage;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', String(active));
  });
}

function startObserver() {
  if (observer) {
    return;
  }
  observer = new MutationObserver((mutations) => {
    if (isApplyingLanguage) {
      return;
    }
    isApplyingLanguage = true;
    disconnectObserver();
    try {
      for (const mutation of mutations) {
        if (mutation.type === 'childList') {
          mutation.addedNodes.forEach((node) => translateNode(node));
        } else if (mutation.type === 'characterData') {
          originalTextNodes.delete(mutation.target);
          translateTextNode(mutation.target);
        } else if (mutation.type === 'attributes') {
          translateElementAttributes(mutation.target);
        }
      }
    } finally {
      reconnectObserver();
      isApplyingLanguage = false;
    }
  });
  reconnectObserver();
}

function disconnectObserver() {
  if (observer) {
    observer.disconnect();
  }
}

function reconnectObserver() {
  if (!observer || !document.body) {
    return;
  }
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: TRANSLATABLE_ATTRIBUTES
  });
}

function translateNode(node) {
  if (!node) {
    return;
  }
  if (node.nodeType === Node.TEXT_NODE) {
    translateTextNode(node);
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE || shouldSkipElement(node)) {
    return;
  }

  translateElementAttributes(node);
  node.childNodes.forEach((child) => translateNode(child));
}

function shouldSkipElement(element) {
  if (SKIP_TAGS.has(element.tagName)) {
    return true;
  }
  return Boolean(element.closest('[data-i18n-skip="true"]'));
}

function translateTextNode(node) {
  if (!node.nodeValue || !node.nodeValue.trim()) {
    return;
  }
  if (!originalTextNodes.has(node)) {
    originalTextNodes.set(node, node.nodeValue);
  }
  const original = originalTextNodes.get(node);
  const nextValue = currentLanguage === 'en' ? original : translateText(original, currentLanguage);
  if (node.nodeValue !== nextValue) {
    node.nodeValue = nextValue;
  }
}

function translateElementAttributes(element) {
  if (shouldSkipElement(element)) {
    return;
  }

  let originals = originalAttributes.get(element);
  if (!originals) {
    originals = {};
    originalAttributes.set(element, originals);
  }

  TRANSLATABLE_ATTRIBUTES.forEach((attribute) => {
    if (!element.hasAttribute(attribute)) {
      return;
    }
    if (!Object.prototype.hasOwnProperty.call(originals, attribute)) {
      originals[attribute] = element.getAttribute(attribute);
    }
    const original = originals[attribute];
    const nextValue = currentLanguage === 'en' ? original : translateText(original, currentLanguage);
    if (element.getAttribute(attribute) !== nextValue) {
      element.setAttribute(attribute, nextValue);
    }
  });
}

function translateDocumentTitle() {
  const original = document.documentElement.dataset.i18nOriginalTitle || document.title;
  document.documentElement.dataset.i18nOriginalTitle = original;
  document.title = currentLanguage === 'en' ? original : translateText(original, currentLanguage);
}
