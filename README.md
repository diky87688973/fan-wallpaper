# 壁纸轮播

Windows 桌面壁纸轮播工具，图片与视频都能轮播。桌面内容由挂在壁纸层的遮盖窗口提供，不写入系统壁纸设置，退出后桌面恢复原样。

## 环境

- Windows 10 / 11
- Python 3.12 或更高
- Microsoft Edge WebView2 Runtime（Windows 11 自带，Windows 10 可能需单独安装）

## 安装

```bat
pip install -r requirements.txt
```

## 运行

```bat
start.bat
```

或直接：

```bat
python wallpaper_app.py
```

启动后只驻留托盘，双击托盘图标打开主窗口，托盘「退出」才结束进程。

## 配置

配置写在程序目录的 `config.json`，界面上的改动会立即落盘。首次运行没有该文件时按默认值启动。字段与默认值：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `image_dir` | `%USERPROFILE%\Pictures\壁纸` | 素材目录，留空回落到该默认值 |
| `interval_minutes` | `5` | 切换间隔，1–1440 分钟 |
| `order` | `sequential` | `sequential` 顺序 / `random` 随机 |
| `allow_video` | `true` | 是否把视频纳入轮播 |
| `muted` | `true` | 视频是否静音 |

`config.example.json` 是入库模板，`config.json` 不入库。

支持的图片扩展名：jpg jpeg jfif png bmp webp gif tif tiff
支持的视频扩展名：mp4 webm mov mkv avi

## 已知限制

- 仅 Windows，依赖 WorkerW 壁纸层与 WebView2
- 仅主显示器，不支持多显示器
- 视频播放期间不按间隔切换，播完再切；十分钟未收到播放结束事件会自动跳过
- 退出时需让 Explorer 重绘桌面，这是唯一触碰系统壁纸接口的位置，只回填读到的原值

## 开发与测试

```bat
pip install -r requirements.txt
pip install pytest pytest-cov ruff

ruff check .
pytest -q
```

`pytest` 会生成 `coverage.json`，随后由脚本按模块校验下限：

```bat
python scripts/check_coverage.py coverage.json
python scripts/check_requirements.py
```

口径排除 `ui.py` 与 `wallview.py`（需交互式桌面与 WebView2），其余七个模块逐条设下限。

测试只覆盖不依赖图形环境的模块（配置、素材枚举、轮播调度）。
窗口挂载、画面表现与退出残留按 [docs/方案.md](docs/方案.md) 的手工验收清单执行。
依赖精确版本见 `requirements.lock`。

## 文档

适用性申报见 [docs/applicability.md](docs/applicability.md)，方案与手工验收清单见 [docs/方案.md](docs/方案.md)。

## 许可

MIT，见 [LICENSE](LICENSE)。
