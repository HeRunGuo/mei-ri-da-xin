# -*- coding: utf-8 -*-
"""
可转债打新
所有可埋伏标的均计算埋伏数据，仅用颜色标记是否符合筛选规则
筛选规则：同意注册、核准期≤1年、百元含权>10、1<PB<2、近期涨幅<20%
"""
import requests
from datetime import datetime, date
import time
import smtplib
from email.mime.text import MIMEText
from requests.exceptions import RequestException

# ====================== 【统一配置区】仅需修改这里 ======================
FILTER_CONFIG = {
    "MIN_HUNDRED_RIGHT": 10.0,
    "MIN_PB": 1.0,
    "MAX_PB": 2.0,
    "MAX_RECENT_RISE": 20.0,
    "APPROVE_VALID_DAYS": 365,
    "AMBUSH_RATIO": 0.6
}

REQUEST_CONFIG = {
    "JSL_AJAX_URL": "https://www.jisilu.cn/data/cbnew/pre_list/",
    "PAGE_SIZE": 200,
    "COOKIE": "",  # 填写集思录登录后的Cookie
    "REQUEST_DELAY": 1,
    "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
}

EMAIL_CONFIG = {
    "host": "smtp.qq.com",
    "user": "2545414090@qq.com",
    "pass": "poongtyekqnzdihc",  # 填写QQ邮箱授权码
    "sender": "2545414090@qq.com",
    "receivers": ["2545414090@qq.com"]
}

# ====================== 【工具函数】数据清洗 ======================
def clean_numeric(value):
    """清洗数值：去除%/--，转float，异常返回0"""
    if not value or str(value) == "--":
        return 0.0
    s = str(value).replace("%", "").replace(",", "")
    try:
        return float(s)
    except:
        return 0.0

def clean_date(date_str):
    """清洗日期，失败返回None"""
    if not date_str:
        return None
    try:
        return datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
    except:
        return None

# ====================== 【核心1】获取集思录数据 ======================
def get_jsl_pending_cb():
    headers = {
        "User-Agent": REQUEST_CONFIG["USER_AGENT"],
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://www.jisilu.cn/data/cbnew/pre_list/",
        "X-Requested-With": "XMLHttpRequest",
        "Cookie": REQUEST_CONFIG["COOKIE"]
    }

    params = {
        "___jsl": f"LST___t={int(time.time() * 1000)}",
        "rp": REQUEST_CONFIG["PAGE_SIZE"],
        "page": 1
    }

    try:
        time.sleep(REQUEST_CONFIG["REQUEST_DELAY"])
        resp = requests.post(REQUEST_CONFIG["JSL_AJAX_URL"], headers=headers, data=params, timeout=15)
        resp.raise_for_status()
        json_data = resp.json()

        if not json_data or "rows" not in json_data:
            print("❌ 未获取到转债数据")
            return []

        data_list = []
        for item in json_data["rows"]:
            cell = item.get("cell", {})
            progress_dt = clean_date(cell.get("progress_dt"))
            amount = clean_numeric(cell.get("amount"))
            price = clean_numeric(cell.get("price"))

            if not progress_dt or amount <= 0 or price <= 0:
                continue

            data = {
                "正股代码": cell.get("stock_id", ""),
                "正股名称": cell.get("stock_nm", ""),
                "转债代码": cell.get("bond_id", ""),
                "转债名称": cell.get("bond_nm", ""),
                "发行规模(亿元)": amount,
                "百元含权(元)": clean_numeric(cell.get("cb_amount")),
                "市净率(PB)": clean_numeric(cell.get("pb")),
                "正股当前价(元)": price,
                "近期涨跌幅(%)": clean_numeric(cell.get("increase_rt")),
                "发行状态": cell.get("progress_nm", ""),
                "核准日期": progress_dt
            }
            data_list.append(data)

        print(f"✅ 成功获取 {len(data_list)} 只待发转债数据")
        return data_list

    except Exception as e:
        print(f"❌ 数据获取失败：{str(e)}")
        return []

# ====================== 【核心2】筛选优质标的（仅标记，不剔除） ======================
def filter_ambush_targets(data_list):
    if not data_list:
        return []
    cfg = FILTER_CONFIG
    today = date.today()
    result = []

    for item in data_list:
        days = (today - item["核准日期"]).days
        is_qualify = (
            days <= cfg["APPROVE_VALID_DAYS"] and
            item["百元含权(元)"] > cfg["MIN_HUNDRED_RIGHT"] and
            cfg["MIN_PB"] < item["市净率(PB)"] < cfg["MAX_PB"] and
            item["近期涨跌幅(%)"] < cfg["MAX_RECENT_RISE"] and
            "同意注册" in item["发行状态"]
        )

        allot = (item["百元含权(元)"] * item["正股当前价(元)"]) / 100
        hold_num = round(1000 / allot) if allot > 0 else 0
        suggest_num = round(hold_num * cfg["AMBUSH_RATIO"])
        capital = round(suggest_num * item["正股当前价(元)"], 2)

        item.update({
            "是否符合筛选": is_qualify,
            "建议埋伏股数": suggest_num,
            "埋伏本金(元)": capital
        })

        if is_qualify and suggest_num > 0:
            result.append(item)
    return result

# ====================== 【核心3】生成HTML邮件内容 ======================
def generate_reminder_content(raw_list, ambush_list):
    today = date.today()
    cfg = FILTER_CONFIG
    html = []

    # 1. 今日申购/上市
    today_sub = [x for x in raw_list if x["核准日期"] == today and "申购" in x["发行状态"]]
    today_list = [x for x in raw_list if x["核准日期"] == today and ("上市" in x["发行状态"] and "上市委通过" not in x["发行状态"])]
    html.append(f"<h3>🔴今日：申购【{len(today_sub)}】只 | 上市【{len(today_list)}】只</h3>")

    if today_sub:
        html.append('<p><font color="red">【今日申购】</font></p>')
        for item in today_sub:
            html.append(f'<p>{item["转债名称"]}({item["转债代码"]})|⚛️{item["正股名称"]}({item["正股代码"]})</p>')
    if today_list:
        html.append('<p><font color="red">【今日上市】</font></p>')
        for item in today_list:
            html.append(f'<p>{item["转债名称"]}({item["转债代码"]})|⚛️{item["正股名称"]}({item["正股代码"]})</p>')
            
    # 2. 未来计划
    future_sub = [x for x in raw_list if x["核准日期"] > today and "申购" in x["发行状态"]]
    future_list = [x for x in raw_list if x["核准日期"] > today and ("上市" in x["发行状态"] and "上市委通过" not in x["发行状态"])]
    html.append(f"<hr><h3>🟢未来：待申购【{len(future_sub)}】只 |待上市【{len(future_list)}】只</h3>")

    if future_sub:
        html.append('<p><font color="green">【待申购】</font></p>')
        for item in future_sub:
            dt_str = item["核准日期"].strftime("%Y-%m-%d")
            html.append(f'<p>{dt_str}|⚛️{item["正股名称"]}({item["正股代码"]})|⚛️{item["转债名称"]}</p>')
    if future_list:
        html.append('<p><font color="green">【待上市】</font></p>')
        for item in future_list:
            dt_str = item["核准日期"].strftime("%Y-%m-%d")
            html.append(f'<p>{dt_str}|⚛️{item["正股名称"]}({item["正股代码"]})|⚛️{item["转债名称"]}</p>')

    # 3. 全量可埋伏标的（表格展示）
    html.append("<hr><h3>🔵可转债埋伏</h3>")
    all_ambush = []
    for item in raw_list:
        days = (today - item["核准日期"]).days
        if days <= cfg["APPROVE_VALID_DAYS"] and "同意注册" in item["发行状态"]:
            all_ambush.append(item)

    if not all_ambush:
        html.append("<p>暂无可埋伏标的</p>")
    else:
        qualified_count = sum(1 for x in all_ambush if x["是否符合筛选"])
        html.append(f'<p>📊可转债埋伏(最低6手)：<b>{len(all_ambush)}</b> 只(符合筛选：<b>{qualified_count}</b>只)</p>')

        # HTML表格
        html.append('''
        <table border="1" cellspacing="0" cellpadding="6" style="width:100%;text-align:center;border-collapse:collapse;">
            <tr style="background:#f5f5f5;">
                <th>正股名称</th>
                <th>正股代码</th>
                <th>百元含权>10(元)</th>
                <th>市净率1-2(PB)</th>
                <th>近期涨跌幅<20(%)</th>
                <th>是否埋伏</th>
                <th>埋伏股数</th>
                <th>埋伏本金(元)</th>
            </tr>
        ''')

        for item in all_ambush:
            if item["是否符合筛选"]:
                tag = '<font color="green"><b>✅</b></font>'
            else:
                tag = '<font color="red"><b>❌</b></font>'

            html.append(f'''
            <tr>
                <td>{item["正股名称"]}</td>
                <td>{item["正股代码"]}</td>
                <td>{item["百元含权(元)"]:.2f}</td>
                <td>{item["市净率(PB)"]:.2f}</td>
                <td>{item["近期涨跌幅(%)"]:.2f}</td>
                <td>{tag}</td>
                <td>{item["建议埋伏股数"]}</td>
                <td>{item["埋伏本金(元)"]:.2f}</td>
            </tr>
            ''')
        html.append('</table>')
    return ''.join(html)

# ====================== 【核心4】邮件发送 ======================
def send_email(content):
    html = f"""
    <html>
        <head><meta charset="utf-8"></head>
        <body>
            <h2>📅 可转债提醒【{datetime.now().strftime("%Y-%m-%d")}】</h2>
            <p>数据来源：<a href="https://www.jisilu.cn/data/cbnew/#pre">集思录转债</a></p>
            <hr>
            {content}
        </body>
    </html>
    """
    msg = MIMEText(html, 'html', 'utf-8')
    msg['Subject'] = '可转债打新埋伏筛选提醒'
    msg['From'] = EMAIL_CONFIG["sender"]
    msg['To'] = ','.join(EMAIL_CONFIG["receivers"])

    try:
        with smtplib.SMTP_SSL(EMAIL_CONFIG["host"], 465) as smtp:
            smtp.login(EMAIL_CONFIG["user"], EMAIL_CONFIG["pass"])
            smtp.send_message(msg)
        print("✅ 邮件发送成功！")
    except Exception as e:
        print(f"❌ 邮件发送失败：{str(e)}")

# ====================== 【核心5】主任务 ======================
def run_main_task():
    raw_list = get_jsl_pending_cb()
    if not raw_list:
        return

    ambush_list = filter_ambush_targets(raw_list)
    print(f"✅ 符合筛选的优质埋伏标的：{len(ambush_list)} 只")

    content = generate_reminder_content(raw_list, ambush_list)
    send_email(content)
# ====================== 程序启动 ======================
if __name__ == '__main__':
        run_main_task()
