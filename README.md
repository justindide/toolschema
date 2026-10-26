# toolschema

**校验工具调用描述与实际行为是否一致。**

`toolschema` —— 比对工具描述、参数模式与实现行为，标出描述与实现不符的地方。

- 零依赖，Python 3.10+ 标准库即可运行
- 单文件，`toolschema.py` 拷走就能用
- 不联网、不写文件

<!-- ipos:install -->
## 安装

零依赖，Python 3.10+ 即可：

```bash
pip install justindide-toolschema
```

装完直接用命令名调用：

```bash
toolschema --help
```

也可以不用安装，直接把 `toolschema.py` 拷走用——它只依赖标准库。

## 为什么需要它

schema 校验工具只查格式；toolschema 额外核对描述与实现是否真的对得上，抓的是「格式没错但语义说反了」。

它遵守下面几条自己定的规矩：

1. **格式对不代表语义对**。描述说「返回列表」而实现返回字典，schema 校验抓不到，但每次调用都会悄悄出错。
2. **只查能机械判定的不一致**，不猜语义。查不出来的明说查不出来。
3. **不改描述**。只报告，让人来改。

## 用法

```bash
python toolschema.py --spec tool.json --source tool.py
python toolschema.py --spec tool.json --source tool.py --json
```

加 `--json` 可以拿到机器可读的结果，便于接到流水线里。

## 已知局限

- 只做机械比对，语义层面的「描述说不说清了」仍需人读。
- 返回类型靠 AST 推断，遇到动态构造的返回值会标为无法判定。
- 不改描述，只报告。

## 跑测试

```bash
python test_toolschema.py
```

测试用独立的断言与临时数据，不污染工作目录。

## 来源与参考

- Python 标准库文档：<https://docs.python.org/3/>
- GitHub 仓库：<https://github.com/justindide/toolschema>

---

## 关于作者

justindide 做工具描述与实现一致性相关的问题。这个工具先替你回答一个具体问题，再谈别的。

- 个人主页：<https://justindide.github.io>
- 仓库：<https://github.com/justindide/toolschema>

## 许可

MIT，见 [LICENSE](LICENSE)。
