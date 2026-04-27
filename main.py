import discord
from discord.ext import commands, tasks
import json, os, re, asyncio
from datetime import datetime, timedelta

# --- 1. การจัดการข้อมูล (คงเดิมจาก freshy) ---
TOKEN = os.getenv('DISCORD_TOKEN')
CONFIG_PATH = '/app/data/config.json'
DB_LEAVE = '/app/data/gang_leaves.json'

def load_json(p, d):
    if os.path.exists(p):
        with open(p, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except:
                return d
    return d

def save_json(p, data):
    if not os.path.exists('/app/data'):
        os.makedirs('/app/data')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 
bot = commands.Bot(command_prefix='!', intents=intents)

def get_thai_time():
    return datetime.now() + timedelta(hours=7)

def validate_date(d_str):
    if not re.match(r"^\d{2}/\d{2}/\d{4}$", d_str):
        return False
    try:
        datetime.strptime(d_str, "%d/%m/%Y")
        return True
    except:
        return False

# --- 2. ระบบตาราง Real-time (คงเดิมจาก freshy) ---
async def update_summary_board():
    cfg = load_json(CONFIG_PATH, {})
    ch_id = cfg.get("realtime_ch")
    if not ch_id:
        return
    channel = bot.get_channel(int(ch_id))
    if not channel:
        return
    
    data = load_json(DB_LEAVE, [])
    now = get_thai_time().date()
    active = []
    
    for e in data:
        try:
            start_dt = datetime.strptime(e['start_date'], "%d/%m/%Y").date()
            end_dt = datetime.strptime(e['end_date'], "%d/%m/%Y").date()
            if start_dt <= now <= end_dt:
                active.append(e)
        except:
            continue

    em = discord.Embed(title="📋 รายชื่อสมาชิกที่แจ้งลา (Real-time)", color=0xf1c40f if active else 0x2ecc71)
    if not active:
        em.description = "✅ **ขณะนี้สมาชิกแก๊ง DMD ทุกคนพร้อมรัน (ยังไม่มีการแจ้งลา)**\n\u200b"
    else:
        txt = ""
        for e in active:
            txt += f"🔹 <@{e['target_id']}> `[{e.get('leave_category','ทั่วไป')}]`"
            if e['user_id'] != e['target_id']:
                txt += f"\n└ **ผู้แจ้งลาแทน:** <@{e['user_id']}>"
            
            dr = e['start_date'] if e['start_date'] == e['end_date'] else f"{e['start_date']} - {e['end_date']}"
            txt += f"\n└ **ลาวันที่:** {dr} `({e['total_days']} วัน)`\n└ **เหตุผลที่ลา:** {e['reason']}\n\n"
        
        footer_info = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        footer_info += f"**📊 สรุปจำนวนคนลาตอนนี้:   {len(active)} คน**\n"
        footer_info += f"**📅 อัปเดตล่าสุด:   {get_thai_time().strftime('%d/%m/%Y %H:%M น.')}**"
        em.description = txt + footer_info

    target = None
    async for m in channel.history(limit=50):
        if m.author == bot.user and m.embeds and len(m.embeds) > 0:
            if m.embeds[0].title == "📋 รายชื่อสมาชิกที่แจ้งลา (Real-time)":
                target = m
                break
    
    if target:
        await target.edit(embed=em)
    else:
        await channel.send(embed=em)

# --- 3. ระบบแจ้งลาและ Log ---
class LeaveModal(discord.ui.Modal):
    def __init__(self, title, s_v, e_v, cat_val, t_id=None, is_f=False, old_re=""):
        super().__init__(title=title)
        self.t_id, self.is_f, self.cat_val = t_id, is_f, cat_val
        self.s_v, self.e_v = s_v, e_v
        
        if not is_f:
            self.s_i = discord.ui.TextInput(label='เริ่มลาวันที่ (วว/ดด/ปปปป)', placeholder='ตัวอย่าง: 25/04/2026', default=s_v, required=True)
            self.e_i = discord.ui.TextInput(label='สิ้นสุดวันที่ (วว/ดด/ปปปป)', placeholder='ตัวอย่าง: 30/04/2026', default=e_v, required=True)
            self.add_item(self.s_i)
            self.add_item(self.e_i)
        
        self.re = discord.ui.TextInput(label='เหตุผลการลา', placeholder='ระบุรายละเอียดเพิ่มเติม...', style=discord.TextStyle.paragraph, default=old_re, required=True)
        self.add_item(self.re)
    
    async def on_submit(self, it: discord.Interaction):
        await it.response.defer(ephemeral=True)
        s = self.s_v if self.is_f else self.s_i.value.strip()
        e = self.e_v if self.is_f else self.e_i.value.strip()
        
        if not validate_date(s) or not validate_date(e):
            err_msg = f"**⚠️ รูปแบบวันที่ไม่ถูกต้อง!**\n\nท่านกรอกมาว่า: เริ่ม `{s}`, สิ้นสุด `{e}` ❌"
            return await it.followup.send(content=err_msg, view=RetryView(self.title, "", "", self.cat_val, self.t_id, self.is_f, self.re.value), ephemeral=True)
        
        today = get_thai_time().date()
        s_dt = datetime.strptime(s, "%d/%m/%Y").date()
        e_dt = datetime.strptime(e, "%d/%m/%Y").date()

        if s_dt < today:
            return await it.followup.send(content="❌ **ไม่สามารถลาย้อนหลังได้** (กรุณาระบุวันที่ตั้งแต่วันนี้เป็นต้นไป)", view=RetryView(self.title, "", "", self.cat_val, self.t_id, self.is_f, self.re.value), ephemeral=True)
        if e_dt < s_dt:
            return await it.followup.send(content="❌ **วันที่สิ้นสุดต้องไม่มาก่อนวันที่เริ่มต้น!**", view=RetryView(self.title, s, "", self.cat_val, self.t_id, self.is_f, self.re.value), ephemeral=True)

        target_uid = self.t_id if self.t_id else str(it.user.id)
        d = load_json(DB_LEAVE, [])
        days = (e_dt - s_dt).days + 1
        
        d.append({
            "user_id": str(it.user.id),
            "target_id": target_uid,
            "leave_category": self.cat_val,
            "start_date": s,
            "end_date": e,
            "total_days": days,
            "reason": self.re.value
        })
        
        save_json(DB_LEAVE, d)
        await update_summary_board()
        
        cfg = load_json(CONFIG_PATH, {})
        log_ch_id = cfg.get("log_ch")
        if log_ch_id:
            log_ch = bot.get_channel(int(log_ch_id))
            if log_ch:
                is_fr = True if self.t_id else False
                log_em = discord.Embed(title="📌 บันทึกการแจ้งลาแทนเพื่อน" if is_fr else "📌 บันทึกการแจ้งลาใหม่", color=0x3498db if is_fr else 0x2ecc71)
                log_em.add_field(name="👤 สมาชิกที่ลา", value=f"<@{target_uid}>", inline=True)
                if is_fr:
                    log_em.add_field(name="👮 ผู้แจ้งลาแทน", value=it.user.mention, inline=True)
                
                date_display = s if s == e else f"{s} - {e}"
                log_em.add_field(name="📅 วันที่", value=f"{date_display} `({days} วัน)`", inline=False)
                
                log_em.add_field(name="📝 ประเภท", value=self.cat_val, inline=True)
                log_em.add_field(name="💬 เหตุผล", value=self.re.value, inline=False)
                log_em.set_footer(text=f"บันทึกเมื่อ: {get_thai_time().strftime('%d/%m/%Y %H:%M')} น.")
                await log_ch.send(embed=log_em)
        
        await it.edit_original_response(content='✅ บันทึกใบลาของท่านเรียบร้อยแล้ว!', view=None)
        await asyncio.sleep(3)
        try:
            await it.delete_original_response()
        except:
            pass

class RetryView(discord.ui.View):
    def __init__(self, title, s, e, cat, t_id, is_f, re_val):
        super().__init__(timeout=60)
        self.title, self.s, self.e, self.cat, self.t_id, self.is_f, self.re_val = title, s, e, cat, t_id, is_f, re_val
    @discord.ui.button(label="📝 แก้ไขข้อมูลที่กรอกผิด", style=discord.ButtonStyle.primary)
    async def retry(self, it, b):
        await it.response.send_modal(LeaveModal(self.title, self.s, self.e, self.cat, self.t_id, self.is_f, self.re_val))
        try:
            await it.delete_original_response()
        except:
            pass

# --- 4. ส่วน Admin (คงเดิมจาก freshy) ---
class AdminSubChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="🔍 ค้นหาห้องที่ต้องการ...", channel_types=[discord.ChannelType.text])
    async def callback(self, it):
        self.view.temp_ch = self.values[0].id
        await it.response.edit_message(content=f"📍 เลือกห้อง: {self.values[0].mention}\n👉 **กรุณากดยืนยันด้านล่างเพื่อบันทึกครับ**")

class AdminSubMenuView(discord.ui.View):
    def __init__(self, cat):
        super().__init__(timeout=120)
        self.cat = cat
        self.temp_ch = None
        self.add_item(AdminSubChannelSelect())
    @discord.ui.button(label="ยืนยันตั้งค่า", style=discord.ButtonStyle.success)
    async def confirm(self, it: discord.Interaction, b):
        if not self.temp_ch:
            return await it.response.send_message("❌ กรุณาเลือกห้องก่อน!", ephemeral=True)
        await it.response.defer(ephemeral=True)
        cfg = load_json(CONFIG_PATH, {})
        cfg[self.cat] = str(self.temp_ch)
        save_json(CONFIG_PATH, cfg)
        
        if self.cat == "leave_ch":
            em = discord.Embed(title="ระบบการแจ้งลาแก๊ง Dark Monday", description="กรุณากดปุ่มด้านล่างเพื่อทำรายการที่ท่านต้องการ", color=0x3498db)
            await bot.get_channel(int(self.temp_ch)).send(embed=em, view=LeaveMainView())
        elif self.cat == "realtime_ch":
            await update_summary_board()
        
        await it.edit_original_response(content=f"✅ ตั้งค่าห้องสำหรับ **{self.cat}** สำเร็จ! (ข้อความนี้จะหายไปเองใน 3 วินาที)", view=None)
        await asyncio.sleep(3)
        try:
            await it.delete_original_response()
        except:
            pass

class AdminCatSelect(discord.ui.Select):
    def __init__(self, opts):
        super().__init__(placeholder="เลือกหัวข้อที่จะตั้งค่า...", options=opts)
    async def callback(self, it):
        cat_final = self.values[0]
        await it.response.edit_message(content=f"🎯 กำลังตั้งค่า: **{cat_final}**", view=AdminSubMenuView(cat_final))

class AdminPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="📍 ตั้งค่าห้องระบบลา", style=discord.ButtonStyle.primary)
    async def set_l(self, it, b):
        opts = [
            discord.SelectOption(label="📝 ห้องปุ่มแจ้งลา", value="leave_ch"),
            discord.SelectOption(label="📋 ตาราง Real-time", value="realtime_ch"),
            discord.SelectOption(label="📌 Log แจ้งลา", value="log_ch"),
            discord.SelectOption(label="📊 ประวัติรายวัน", value="daily_ch"),
            discord.SelectOption(label="📊 สรุปประวัติรายสัปดาห์", value="weekly_ch")
        ]
        await it.response.send_message("🛠 เลือกหัวข้อที่ต้องการตั้งค่า:", view=SubMenuView(it, AdminCatSelect(opts)), ephemeral=True)

# --- 5. งานรายวัน 00:05 น. และ รายสัปดาห์ 00:10 น. ---
@tasks.loop(minutes=1)
async def daily_report_task():
    n = get_thai_time()
    # รายวัน 00:05 น.
    if n.hour == 0 and n.minute == 5:
        cfg = load_json(CONFIG_PATH, {})
        ch_id = cfg.get("daily_ch", 0)
        if ch_id:
            ch = bot.get_channel(int(ch_id))
            if ch:
                d = load_json(DB_LEAVE, [])
                nd = n.date()
                ac = []
                counts = {}
                for e in d:
                    try:
                        s_d = datetime.strptime(e['start_date'], "%d/%m/%Y").date()
                        e_d = datetime.strptime(e['end_date'], "%d/%m/%Y").date()
                        if s_d <= nd <= e_d:
                            ac.append(e)
                            cat = e.get('leave_category', 'ทั่วไป')
                            counts[cat] = counts.get(cat, 0) + 1
                    except: continue
                
                em = discord.Embed(title=f"📊 สรุปประวัติการลาของวันที่ {n.strftime('%d/%m/%Y')}", color=0x9b59b6)
                if not ac:
                    em.description = "✅ **วันนี้สมาชิกแก๊ง DMD ทุกคนพร้อมรัน (ไม่มีใครลา)**\n\n**👥 รวมสมาชิกที่ลาทั้งหมด:   0 คน**\n\u200b"
                else:
                    msg = ""
                    for i in ac:
                        tg = bot.get_user(int(i['target_id']))
                        tn = tg.display_name if tg else f"ID: {i['target_id']}"
                        msg += f"📍 **{tn}** `[{i.get('leave_category','ทั่วไป')}]` | {i['reason']}"
                        if i['user_id'] != i['target_id']:
                            su = bot.get_user(int(i['user_id']))
                            sn = u.display_name if su else f"ID: {i['user_id']}"
                            msg += f" **(แจ้งแทนโดย: {sn})**"
                        msg += "\n"
                    
                    summary_msg = "\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n**📊 สรุปยอดรวม:**\n"
                    for cat_name, count in counts.items():
                        summary_msg += f"• {cat_name} : {count} คน\n"
                    summary_msg += f"**👥 รวมสมาชิกที่ลาทั้งหมด {len(ac)} คน**\n\u200b"
                    em.description = msg + summary_msg
                
                em.set_footer(text=f"บันทึกเมื่อ: {n.strftime('%H:%M')} น.")
                await ch.send(embed=em)

    # รายสัปดาห์ ทุกวันจันทร์ 00:10 น.
    if n.weekday() == 0 and n.hour == 0 and n.minute == 10:
        cfg = load_json(CONFIG_PATH, {})
        w_ch_id = cfg.get("weekly_ch")
        if w_ch_id:
            w_ch = bot.get_channel(int(w_ch_id))
            if w_ch:
                d = load_json(DB_LEAVE, [])
                end_range = n.date() - timedelta(days=1)
                start_range = end_range - timedelta(days=6)
                
                w_ac, user_days, cat_counts = [], {}, {}
                for e in d:
                    try:
                        s_d = datetime.strptime(e['start_date'], "%d/%m/%Y").date()
                        e_d = datetime.strptime(e['end_date'], "%d/%m/%Y").date()
                        overlap_start = max(s_d, start_range)
                        overlap_end = min(e_d, end_range)
                        if overlap_start <= overlap_end:
                            w_ac.append(e)
                            days = (overlap_end - overlap_start).days + 1
                            user_days[e['target_id']] = user_days.get(e['target_id'], 0) + days
                            cat = e.get('leave_category', 'ทั่วไป')
                            cat_counts[cat] = cat_counts.get(cat, 0) + 1
                    except: continue

                em = discord.Embed(title="📊 สรุปยอดการลาสะสมรายสัปดาห์ (DMD Weekly Report)", color=0x5865f2)
                em.description = f"**ประจำวันที่ {start_range.strftime('%d/%m/%Y')} - {end_range.strftime('%d/%m/%Y')}**\n\n"
                
                if not w_ac:
                    em.description += "✅ **สัปดาห์ที่ผ่านมาไม่มีสมาชิกแจ้งลา**"
                else:
                    max_cat = max(cat_counts, key=cat_counts.get) if cat_counts else "-"
                    em.description += f"**🏆 สถิติภาพรวมสัปดาห์นี้:**\n• จำนวนใบลาทั้งหมด: `{len(w_ac)} ใบ`\n• รวมวันลาสะสม: `{sum(user_days.values())} วัน`\n• ประเภทการลาที่มีคนลาเยอะที่สุด: `{max_cat} ({cat_counts.get(max_cat, 0)} คน)`\n\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                    
                    top_users = sorted(user_days.items(), key=lambda x: x[1], reverse=True)[:3]
                    top_msg = "**🥇 สมาชิกที่ลาเยอะที่สุด (Top 3):**\n"
                    for i, (uid, dcount) in enumerate(top_users, 1):
                        uobj = bot.get_user(int(uid))
                        un = uobj.display_name if uobj else f"ID: {uid}"
                        top_msg += f"{i}. **{un}** : ลาสะสม `{dcount} วัน`\n"
                    
                    cat_msg = "\n**📅 สรุปยอดลาแยกตามประเภท:**\n"
                    for cname, ccount in cat_counts.items():
                        cat_msg += f"• {cname} : `{ccount} คน`\n"
                    
                    em.description += top_msg + cat_msg + "\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
                
                em.set_footer(text=f"บันทึกเมื่อ: {n.strftime('%H:%M')} น.")
                await w_ch.send(embed=em)

# --- 6. ระบบยกเลิกใบลา ---
class CancelReasonModal(discord.ui.Modal):
    def __init__(self, target_idx, od):
        super().__init__(title="ระบุเหตุผลการยกเลิก")
        self.target_idx, self.od = target_idx, od
        self.reason = discord.ui.TextInput(label='เหตุผลที่ยกเลิก', placeholder='ระบุเหตุผลที่นี่...', style=discord.TextStyle.paragraph, required=True)
        self.add_item(self.reason)
    
    async def on_submit(self, it: discord.Interaction):
        await it.response.defer(ephemeral=True)
        d = load_json(DB_LEAVE, [])
        if 0 <= self.target_idx < len(d):
            d.pop(self.target_idx)
            save_json(DB_LEAVE, d)
            await update_summary_board()
            cfg = load_json(CONFIG_PATH, {})
            log_ch_id = cfg.get("log_ch")
            if log_ch_id:
                log_ch = bot.get_channel(int(log_ch_id))
                if log_ch:
                    log_em = discord.Embed(title="📌 บันทึกยกเลิกการแจ้งลา", color=0xe74c3c)
                    log_em.add_field(name="👤 สมาชิกที่ลา", value=f"<@{self.od['target_id']}>", inline=True)
                    if self.od['user_id'] != str(it.user.id): 
                        log_em.add_field(name="👮 ผู้ยกเลิก", value=it.user.mention, inline=True)
                    dr = self.od['start_date'] if self.od['start_date'] == self.od['end_date'] else f"{self.od['start_date']} - {self.od['end_date']}"
                    log_em.add_field(name="📅 วันที่เคยแจ้ง", value=f"{dr} `({self.od.get('total_days', 1)} วัน)`", inline=False)
                    log_em.add_field(name="📝 ประเภท", value=self.od.get('leave_category', 'ทั่วไป'), inline=True)
                    log_em.add_field(name="💬 เหตุผลที่เคยแจ้ง", value=self.od.get('reason', '-'), inline=False)
                    log_em.add_field(name="🛑 เหตุผลที่ยกเลิก", value=self.reason.value, inline=False)
                    log_em.set_footer(text=f"บันทึกเมื่อ: {get_thai_time().strftime('%d/%m/%Y %H:%M')} น.")
                    await log_ch.send(embed=log_em)
            
            await it.edit_original_response(content=f"✅ ยกเลิกใบลาของท่านเรียบร้อยแล้ว!", view=None)
        await asyncio.sleep(3)
        try: await it.delete_original_response()
        except: pass

class ConfirmCancelView(discord.ui.View):
    def __init__(self, target_idx, od):
        super().__init__(timeout=60)
        self.target_idx, self.od = target_idx, od
    @discord.ui.button(label="✅ ยืนยันการยกเลิก", style=discord.ButtonStyle.success)
    async def confirm(self, it, b):
        await it.response.send_modal(CancelReasonModal(self.target_idx, self.od))
    @discord.ui.button(label="❌ ไม่ยกเลิกแล้ว", style=discord.ButtonStyle.danger)
    async def cancel(self, it, b):
        await it.response.defer()
        try: await it.delete_original_response()
        except: pass

class CancelSelect(discord.ui.Select):
    def __init__(self, opts):
        super().__init__(placeholder="📋 เลือกรายการที่จะยกเลิก...", options=opts)
    async def callback(self, it):
        await it.response.defer(ephemeral=True)
        idx = int(self.values[0])
        d = load_json(DB_LEAVE, [])
        if 0 <= idx < len(d):
            od = d[idx]
            dr = od['start_date'] if od['start_date'] == od['end_date'] else f"{od['start_date']} - {od['end_date']}"
            txt = f"⚠️ **แน่ใจหรือไม่ที่จะยกเลิกการลานี้?**\n👤 **คนลา:** <@{od['target_id']}>\n📝 **ประเภท:** `{od.get('leave_category','ทั่วไป')}`\n📅 **วันที่:** {dr} `({od.get('total_days', 1)} วัน)`\n💬 **เหตุผลเดิม:** {od.get('reason','-')}"
            await it.edit_original_response(content=txt, view=ConfirmCancelView(idx, od))

# --- 7. ระบบแก้ไขวันสิ้นสุด ---
async def process_edit_leave(it, idx, od, new_end_str):
    d = load_json(DB_LEAVE, [])
    old_e = od['end_date']
    if 0 <= idx < len(d):
        d[idx]['end_date'] = new_end_str
        d[idx]['total_days'] = (datetime.strptime(new_end_str, "%d/%m/%Y") - datetime.strptime(od['start_date'], "%d/%m/%Y")).days + 1
        save_json(DB_LEAVE, d)
        await update_summary_board()
        cfg = load_json(CONFIG_PATH, {})
        log_ch_id = cfg.get("log_ch")
        if log_ch_id:
            log_ch = bot.get_channel(int(log_ch_id))
            if log_ch:
                # ปรับปรุง Log ตามสั่ง: ดึงข้อมูล ประเภท, ช่วงเวลาเดิม และเหตุผลเดิมมาโชว์
                log_em = discord.Embed(title="📌 บันทึกการแก้ไขวันสิ้นสุดการลา", color=0xffffff)
                log_em.add_field(name="👤 สมาชิกที่ลา", value=f"<@{od['target_id']}>", inline=True)
                if od['target_id'] != str(it.user.id):
                    log_em.add_field(name="👮 ผู้แก้ไข", value=it.user.mention, inline=True)
                
                log_em.add_field(name="📝 ประเภท", value=od.get('leave_category', 'ทั่วไป'), inline=True)
                log_em.add_field(name="📅 ช่วงเวลาเดิม", value=f"{od['start_date']} - {od['end_date']}", inline=False)
                log_em.add_field(name="🔹 วันที่สิ้นสุดใหม่", value=f"**{new_end_str}**", inline=True)
                log_em.add_field(name="📊 สถานะ", value=f"เปลี่ยนจาก `{old_e}` เป็น `{new_end_str}`", inline=False)
                log_em.add_field(name="💬 เหตุผลเดิมที่แจ้ง", value=od.get('reason', '-'), inline=False)
                
                log_em.set_footer(text=f"บันทึกเมื่อ: {get_thai_time().strftime('%d/%m/%Y %H:%M')} น.")
                await log_ch.send(embed=log_em)
        
        await it.edit_original_response(content=f"✅ แก้ไขวันสิ้นสุดของท่านเรียบร้อยแล้ว!", embed=None, view=None)
        await asyncio.sleep(3)
        try: await it.delete_original_response()
        except: pass

class ConfirmEditView(discord.ui.View):
    def __init__(self, idx, od, new_end):
        super().__init__(timeout=60)
        self.idx, self.od, self.new_end = idx, od, new_end
    @discord.ui.button(label="✅ ยืนยันการแก้ไข", style=discord.ButtonStyle.success)
    async def confirm(self, it, b):
        await it.response.defer(ephemeral=True)
        await process_edit_leave(it, self.idx, self.od, self.new_end)
    @discord.ui.button(label="📅 เลือกวันสิ้นสุดใหม่", style=discord.ButtonStyle.primary)
    async def reselect(self, it, b):
        await it.response.edit_message(content="📅 **กรุณาเลือกวันที่สิ้นสุดใหม่อีกครั้ง:**", embed=None, view=SubMenuView(it, EditDateSelect(self.idx, self.od)))
    @discord.ui.button(label="❌ ยกเลิก", style=discord.ButtonStyle.danger)
    async def cancel(self, it, b):
        await it.response.defer()
        try: await it.delete_original_response()
        except: pass

class EditDateModal(discord.ui.Modal):
    def __init__(self, idx, od, parent_it=None):
        super().__init__(title="ระบุวันที่กลับมาจริง")
        self.idx, self.od, self.parent_it = idx, od, parent_it
        self.new_e = discord.ui.TextInput(label='วันที่กลับมาจริง (วว/ดด/ปปปป)', placeholder='ตัวอย่าง: 28/04/2026', required=True)
        self.add_item(self.new_e)
    async def on_submit(self, it: discord.Interaction):
        val = self.new_e.value.strip()
        if not validate_date(val): return await it.response.send_message("❌ รูปแบบวันที่ผิด!", ephemeral=True)
        today = get_thai_time().date()
        s_dt = datetime.strptime(self.od['start_date'], "%d/%m/%Y").date()
        new_e_dt = datetime.strptime(val, "%d/%m/%Y").date()
        if new_e_dt < today or new_e_dt < s_dt: return await it.response.send_message("❌ วันที่ผิดพลาด!", ephemeral=True)
        
        # เมื่อกรอกข้อมูลเสร็จ ลบข้อความลับ "✏️ กำลังระบุวันที่..." เดิมออกทันที
        if self.parent_it:
            try: await self.parent_it.delete_original_response()
            except: pass
            
        # แสดง Embed สรุปสีขาวให้ยืนยันอีกครั้งตามรูปที่ต้องการ
        em = discord.Embed(title="⚠️ ยืนยันการแก้ไขวันสิ้นสุดการลา", color=0xffffff)
        em.add_field(name="👤 สมาชิกที่ลา", value=f"<@{self.od['target_id']}>", inline=True)
        em.add_field(name="📝 ประเภท", value=self.od.get('leave_category', 'ทั่วไป'), inline=True)
        em.add_field(name="📅 ช่วงเวลาเดิม", value=f"{self.od['start_date']} - {self.od['end_date']}", inline=False)
        em.add_field(name="🔹 เปลี่ยนวันสิ้นสุดเป็น", value=f"**{val}**", inline=False)
        await it.response.send_message(embed=em, view=ConfirmEditView(self.idx, self.od, val), ephemeral=True)

class EditDateSelect(discord.ui.Select):
    def __init__(self, idx, od, parent_it=None):
        self.idx, self.od, self.parent_it = idx, od, parent_it
        s_dt = datetime.strptime(od['start_date'], "%d/%m/%Y")
        e_dt = datetime.strptime(od['end_date'], "%d/%m/%Y")
        opts = []
        for i in range((e_dt - s_dt).days + 1):
            if i >= 24: break
            d_str = (s_dt + timedelta(days=i)).strftime("%d/%m/%Y")
            opts.append(discord.SelectOption(label=d_str, value=d_str))
        opts.append(discord.SelectOption(label="➕ ระบุวันที่เอง", value="manual", emoji="✏️"))
        super().__init__(placeholder="📅 เลือกวันที่กลับมาจริง...", options=opts)
    async def callback(self, it: discord.Interaction):
        if self.values[0] == "manual": 
            # ส่ง Modal และส่ง Interaction ต้นทางไปด้วยเพื่อสั่งลบในภายหลัง
            await it.response.send_modal(EditDateModal(self.idx, self.od, self.parent_it))
            try:
                await it.edit_original_response(content="✏️ กำลังระบุวันที่กลับมาจริงในหน้าต่างกรอกข้อมูล...", view=None, embed=None)
            except:
                pass
        else:
            val = self.values[0]
            if datetime.strptime(val, "%d/%m/%Y").date() < get_thai_time().date(): return await it.response.send_message("❌ ไม่สามารถลาย้อนหลังได้", ephemeral=True)
            em = discord.Embed(title="⚠️ ยืนยันการแก้ไขวันสิ้นสุดการลา", color=0xffffff)
            em.add_field(name="👤 สมาชิกที่ลา", value=f"<@{self.od['target_id']}>", inline=True)
            em.add_field(name="📝 ประเภท", value=self.od.get('leave_category', 'ทั่วไป'), inline=True)
            em.add_field(name="📅 ช่วงเวลาเดิม", value=f"{self.od['start_date']} - {self.od['end_date']}", inline=False)
            em.add_field(name="🔹 เปลี่ยนวันสิ้นสุดเป็น", value=f"**{val}**", inline=False)
            await it.response.edit_message(content=None, embed=em, view=ConfirmEditView(self.idx, self.od, val))

class EditLeaveSelect(discord.ui.Select):
    def __init__(self, opts, parent_it=None):
        super().__init__(placeholder="✏️ เลือกใบลาที่ต้องการแก้...", options=opts)
        self.parent_it = parent_it
    async def callback(self, it):
        await it.response.defer(ephemeral=True)
        idx = int(self.values[0])
        d = load_json(DB_LEAVE, [])
        if 0 <= idx < len(d):
            await it.edit_original_response(content="📅 **เลือกวันที่สิ้นสุดใหม่:**", view=SubMenuView(it, EditDateSelect(idx, d[idx], it)))

# --- 8. เมนูหลัก 4 ปุ่ม (ปรับ Dropdown ละเอียด) ---
class LeaveMainView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="📝 แจ้งลา", style=discord.ButtonStyle.success, custom_id="v_l_final_vMaster_DMD_master_1")
    async def l_me(self, it, b):
        await it.response.send_message("🤔 ลาช่วงไหน:", view=SubMenuView(it, DateSelect()), ephemeral=True)
    @discord.ui.button(label="👥 ลาแทนเพื่อน", style=discord.ButtonStyle.primary, custom_id="v_l_final_vMaster_DMD_master_2")
    async def l_fr(self, it, b):
        await it.response.send_message("👤 เลือกเพื่อน:", view=SubMenuView(it, FriendSelect()), ephemeral=True)
    
    @discord.ui.button(label="❌ ยกเลิกการลา", style=discord.ButtonStyle.danger, custom_id="v_l_final_vMaster_DMD_master_3")
    async def l_cn(self, it, b):
        d = load_json(DB_LEAVE, [])
        u_id, now_date, opts = str(it.user.id), get_thai_time().date(), []
        for i, e in enumerate(d):
            if e['user_id'] == u_id or e['target_id'] == u_id:
                try:
                    if datetime.strptime(e['end_date'], "%d/%m/%Y").date() < now_date: continue
                except: continue
                tg = bot.get_user(int(e['target_id']))
                tn = tg.display_name if tg else f"ID: {e['target_id']}"
                dr = e['start_date'] if e['start_date'] == e['end_date'] else f"{e['start_date']} - {e['end_date']}"
                
                opts.append(discord.SelectOption(
                    label=f"{tn} | {dr} ({e.get('total_days', 1)} วัน)",
                    description=f"ประเภท: {e.get('leave_category','ทั่วไป')} | เหตุผล: {e.get('reason','-')[:20]}...",
                    value=str(i)
                ))
        if not opts: return await it.response.send_message("❌ ไม่พบรายการ", ephemeral=True)
        await it.response.send_message("📋 เลือกใบลาที่จะยกเลิก:", view=SubMenuView(it, CancelSelect(opts[:25])), ephemeral=True)
    
    @discord.ui.button(label="✏️ แก้ไขวันสิ้นสุดการลา", style=discord.ButtonStyle.secondary, custom_id="v_l_final_vMaster_DMD_master_4")
    async def l_ed(self, it, b):
        d = load_json(DB_LEAVE, [])
        u_id, now_date, opts = str(it.user.id), get_thai_time().date(), []
        for i, e in enumerate(d):
            if (e['user_id'] == u_id or e['target_id'] == u_id) and e['start_date'] != e['end_date']:
                try:
                    if datetime.strptime(e['end_date'], "%d/%m/%Y").date() < now_date: continue
                except: continue
                tg = bot.get_user(int(e['target_id']))
                tn = tg.display_name if tg else f"ID: {e['target_id']}"
                dr = e['start_date'] if e['start_date'] == e['end_date'] else f"{e['start_date']} - {e['end_date']}"
                
                opts.append(discord.SelectOption(
                    label=f"{tn} | {dr} ({e.get('total_days', 1)} วัน)",
                    description=f"ประเภท: {e.get('leave_category','ทั่วไป')} | เหตุผล: {e.get('reason','-')[:20]}...",
                    value=str(i)
                ))
        if not opts: return await it.response.send_message("❌ ไม่พบรายการ", ephemeral=True)
        # ส่ง interaction (it) เข้าไปในระบบเพื่อเอาไว้ใช้สั่งลบข้อความลับในภายหลัง
        await it.response.send_message("✏️ เลือกใบลาที่จะแก้:", view=SubMenuView(it, EditLeaveSelect(opts[:25], it)), ephemeral=True)

class FriendSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="👤 เลือกเพื่อน...", min_values=1, max_values=1)
    async def callback(self, it):
        await it.response.edit_message(content=f"🎯 ลาแทนคุณ: {self.values[0].mention}", view=SubMenuView(it, DateSelect(t_id=str(self.values[0].id))))

class SubMenuView(discord.ui.View):
    def __init__(self, o_it, item=None):
        super().__init__(timeout=60)
        self.o_it = o_it
        if item: self.add_item(item)
    @discord.ui.button(label="ปิดเมนู", style=discord.ButtonStyle.danger, row=3)
    async def cls(self, it, b):
        await it.response.defer()
        try: await it.delete_original_response()
        except: pass

class DateSelect(discord.ui.Select):
    def __init__(self, t_id=None):
        self.t_id = t_id
        opts = [discord.SelectOption(label="ลาวันนี้", value="t"), discord.SelectOption(label="ลาพรุ่งนี้", value="tm"), discord.SelectOption(label="ลาแบบระบุวันเอง", value="m")]
        super().__init__(placeholder="📅 เลือกวันที่ลา...", options=opts)
    async def callback(self, it):
        now = get_thai_time()
        val = self.values[0]
        if val == "t": title, s, e, is_fixed = "ลาวันนี้", now.strftime("%d/%m/%Y"), now.strftime("%d/%m/%Y"), True
        elif val == "tm": title, s, e, is_fixed = "ลาพรุ่งนี้", (now + timedelta(days=1)).strftime("%d/%m/%Y"), (now + timedelta(days=1)).strftime("%d/%m/%Y"), True
        else: title, s, e, is_fixed = "ลาแบบระบุวันเอง", "", "", False
        await it.response.edit_message(content=f"✅ เลือกช่วงเวลา: **{title}**\n👉 กรุณาเลือกประเภทการลาด้านล่าง:", view=SubMenuView(it, LeaveCategorySelect(title, s, e, self.t_id, is_fixed)))

class LeaveCategorySelect(discord.ui.Select):
    def __init__(self, m_title, s_v, e_v, t_id=None, is_f=False):
        self.m_title, self.s_v, self.e_v, self.t_id, self.is_f = m_title, s_v, e_v, t_id, is_f
        opts = [discord.SelectOption(label=x, emoji="📝") for x in ["ลาพีคไทม์", "ลาแอร์ดรอป 21:00 น.", "ลาแอร์ดรอป 00:00 น.", "ลาอีเธอร์ยักษ์", "ลาสกายฟอล", "ลาซ้อม", "ลาอื่นๆ (ระบุในเหตุผลการลา)"]]
        super().__init__(placeholder="📝 เลือกประเภทการลา...", options=opts)
    async def callback(self, it):
        await it.response.send_modal(LeaveModal(self.m_title, self.s_v, self.e_v, self.values[0], self.t_id, self.is_f))
        try: await it.delete_original_response()
        except: pass

@bot.command()
@commands.has_role("Admin")
async def admin(ctx):
    await ctx.send(embed=discord.Embed(title="🕹 Dark Monday Admin Panel"), view=AdminPanelView())

@bot.event
async def on_ready():
    bot.add_view(LeaveMainView())
    print('Bot freshy Online')
    if not daily_report_task.is_running(): daily_report_task.start()

bot.run(TOKEN)