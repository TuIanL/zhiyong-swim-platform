#!/usr/bin/env python3
"""把 PostgreSQL JUnit 中的失败场景提升为 CI check 注解。

只在失败分支调用；不改变测试结论，只让失败场景名与断言消息出现在注解里，
避免需要下载 artifact 才能定位。无法读取 JUnit 时输出一条提示注解。
"""
import glob
import xml.etree.ElementTree as ET

paths = glob.glob("var/postgresql-junit.xml")
if not paths:
    print("::error::没有生成 postgresql-junit.xml，无法列出失败场景")
    raise SystemExit(0)

emitted = 0
for case in ET.parse(paths[0]).getroot().iter("testcase"):
    failure = case.find("failure")
    if failure is None:
        failure = case.find("error")
    if failure is None:
        continue
    message = (failure.get("message") or "").replace("\n", " ")[:300]
    print(f"::error::FAILED {case.get('classname')}::{case.get('name')} :: {message}")
    emitted += 1
if not emitted:
    print("::error::JUnit 中没有失败用例记录，失败可能来自收集或环境阶段")
