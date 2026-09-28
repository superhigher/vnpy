"""
CTP 看穿式认证登录测试（测试点 1）
验证：登录测试账号通过期货公司交易信息系统完成看穿式认证、完成账号登录
"""
from time import sleep

from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine
from vnpy.trader.event import EVENT_LOG
from vnpy.trader.object import LogData
from vnpy_ctp import CtpGateway

# 测试账户3
SETTING = {
    "用户名": "21013",
    "密码": "zwy123321",
    "经纪商代码": "8080",
    "交易服务器": "59.36.3.115:27226",
    "行情服务器": "59.36.3.115:27236",
    "产品名称": "client_vnpy_4.4.0",   # appid
    "授权编码": "SVUYNTZH8Q92CUY7",
    "柜台环境": "实盘",
}

logs: list[str] = []
auth_ok = False
login_ok = False
settle_ok = False


def process_log(event):
    log: LogData = event.data
    msg = log.msg
    logs.append(msg)
    print(f"[{log.time}] {msg}")
    global auth_ok, login_ok, settle_ok
    if "授权验证成功" in msg:
        auth_ok = True
    if "交易服务器登录成功" in msg:
        login_ok = True
    if "结算信息确认成功" in msg:
        settle_ok = True


def main():
    global auth_ok, login_ok, settle_ok
    event_engine = EventEngine()
    event_engine.register(EVENT_LOG, process_log)
    main_engine = MainEngine(event_engine)
    main_engine.add_gateway(CtpGateway)

    print("=== CTP 看穿式认证登录测试 ===")
    print(f"登录账号: {SETTING['用户名']}")
    print(f"appid(产品名称): {SETTING['产品名称']}")
    print(f"授权编码: {SETTING['授权编码']}")
    print(f"经纪商代码: {SETTING['经纪商代码']}")
    print(f"交易服务器: {SETTING['交易服务器']}")
    print()

    gateway = main_engine.get_gateway("CTP")
    gateway.connect(SETTING)

    # 最多等 90 秒完成 认证->登录->结算确认
    for _ in range(90):
        if settle_ok:
            break
        sleep(1)

    print()
    print("=== 测试结果 ===")
    print(f"看穿式认证(授权验证): {'通过' if auth_ok else '未通过'}")
    print(f"账号登录(交易服务器): {'成功' if login_ok else '失败'}")
    print(f"结算单确认: {'成功' if settle_ok else '未完成'}")

    if auth_ok and login_ok:
        print("TEST_RESULT: PASS")
    else:
        print("TEST_RESULT: FAIL")

    print("FLUSHING")
    import sys
    sys.stdout.flush()
    # 强制退出，避免 CTP API 线程 join 卡死
    import os
    os._exit(0 if (auth_ok and login_ok) else 1)


if __name__ == "__main__":
    main()
