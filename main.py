import discord
from discord.ext import commands, tasks
import json, os, re, asyncio
from datetime import datetime, timedelta

# --- 1. การจัดการข้อมูล (คงเดิมจาก freshy) ---
TOKEN = os.getenv('DISCORD_TOKEN')
CONFIG_PATH = '/app/data/config.json'
DB_LEAVE = '/app/data/gang_leaves.json'
LONG_SEP = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"

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
        em.description = "✅ **ขณะนี้สมาชิกแก๊ง DMD ทุกคนพร้อมรัน (ยังไม่มีการแจ้งลา)**\n\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
    else:
        txt = ""
        for e in active:
            txt += f"🔹 <@{e['target_id']}> `[{e.get('leave_category','ทั่วไป')}]`"
            if e['user_id'] != e['target_id']:
                txt += f"\n└ **ผู้แจ้งลาแทน:** <@{e['user_id']}>"
            
            dr = e['start_date'] if e['start_date'] == e['end_date'] else f"{e['start_date']} - {e['end_date']}"
            txt += f"\n└ **ลาวันที่:** {dr} `({e['total_days']} วัน)`\n└ **เหตุผลที่ลา:** {e['reason']}\n\n"
        
        footer_info = f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
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

# --- 3. ระบบแจ้งลาและ Log (คงเดิมจาก freshy) ---
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
        
        await it.edit_original_response(content=f"✅ ตั้งค่าห้องสำหรับ **{self.cat}** สำเร็จ!", view=None)
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

# --- 5. งานรายวัน และ รายสัปดาห์ (ปรับปรุงตามสั่ง) ---
@tasks.loop(minutes=1)
async def daily_report_task():
    n = get_thai_time()
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
                    em.description = "✅ **วันนี้สมาชิกแก๊ง DMD ทุกคนพร้อมรัน (ไม่มีใครลา)**\n\n**👥 รวมสมาชิกที่ลาทั้งหมด:   0 คน**"
                else:
                    msg = ""
                    for i in ac:
                        tg = bot.get_user(int(i['target_id']))
                        tn = tg.display_name if tg else f"ID: {i['target_id']}"
                        msg += f"🔹 **{tn}** `[{i.get('leave_category','ทั่วไป')}]`"
                        msg += f"\n└ **เหตุผล:** {i['reason']}" # เหตุผลลงบรรทัดใหม่
                        if i['user_id'] != i['target_id']:
                            msg += f" **(แจ้งแทนโดย: <@{i['user_id']}>)**"
                        msg += "\n\n"
                    
                    summary_msg = f"{LONG_SEP}\n**📊 สรุปยอดรวม:**\n" # เส้นยาวตามสั่ง
                    for cat_name, count in counts.items():
                        summary_msg += f"• {cat_name} : {count} คน\n"
                    summary_msg += f"**👥 รวมสมาชิกที่ลาทั้งหมด {len(ac)} คน**\n{LONG_SEP}"
                    em.description = msg + summary_msg
                
                em.set_footer(text=f"บันทึกเมื่อ: {n.strftime('%H:%M')} น.")
                await ch.send(embed=em)

    if n.weekday() == 0 and n.hour == 0 and n.minute == 10:
        cfg = load_json(CONFIG_PATH, {})
        w_ch_id = cfg.get("weekly_ch")
        if w_ch_id:
            w_ch = bot.get_channel(int(w_ch_id))
            if w_ch:
                guild = w_ch.guild
                target_role_id = 1456228588968739028
                exclude_role_id = 1498319593939144755
                valid_members = [m for m in guild.members if any(r.id == target_role_id for r in m.roles) and not any(r.id == exclude_role_id for r in m.roles)]
                
                end_range = n.date() - timedelta(days=1)
                start_range = end_range - timedelta(days=6)
                d = load_json(DB_LEAVE, [])
                leaver_stats, non_leavers = [], []
                
                for m in valid_members:
                    total_days, has_leave = 0, False
                    for e in d:
                        if e['target_id'] == str(m.id):
                            try:
                                s_d = datetime.strptime(e['start_date'], "%d/%m/%Y").date()
                                e_d = datetime.strptime(e['end_date'], "%d/%m/%Y").date()
                                overlap_s, overlap_e = max(s_d, start_range), min(e_d, end_range)
                                if overlap_s <= overlap_e:
                                    total_days += (overlap_e - overlap_s).days + 1
                                    has_leave = True
                            except: continue
                    if has_leave: leaver_stats.append(f"{m.display_name} (รวม {total_days} วัน)")
                    else: non_leavers.append(m.display_name)

                em = discord.Embed(title="📊 สรุปรายชื่อการแจ้งลาประจำสัปดาห์", color=0x2b2d31)
                em.description = f"📅 **ประจำวันที่:** `{start_range.strftime('%d/%m/%Y')}` - `{end_range.strftime('%d/%m/%Y')}`\n\n"
                txt_left = "__**✅ สมาชิกที่แจ้งลา**__\n" + ("\n".join(leaver_stats) if leaver_stats else "ไม่มีรายชื่อ")
                txt_ready = "\n\n__**❌ สมาชิกที่ไม่ลาเลย**__\n" + ("\n".join(non_leavers) if non_leavers else "ไม่มีรายชื่อ")
                
                total_all = len(valid_members)
                leave_c, active_c = len(leaver_stats), len(non_leavers)
                act_pc = (active_c / total_all * 100) if total_all > 0 else 0
                
                stats_msg = f"\n\n{LONG_SEP}\n**📊 สถิติแก๊งรอบสัปดาห์**\n• สมาชิกทั้งหมด: `{total_all} คน`\n• จำนวนคนที่แจ้งลา: `{leave_c} คน`\n• จำนวนคนที่แอคทีฟ (ไม่ลา): `{active_c} คน`\n• **เปอร์เซ็นต์ความแอคทีฟ:** `{act_pc:.1f}%`\n{LONG_SEP}"
                em.description += txt_left + txt_ready + stats_msg
                em.set_footer(text=f"บันทึกเมื่อ: {n.strftime('%d/%m/%Y %H:%M น.')}")
                await w_ch.send(embed=em)

# --- 6. ระบบยกเลิก (คงเดิมจาก freshy) ---
class CancelReasonModal(discord.ui.Modal):
    def __init__(self, target_idx, od):
        super().__init__(title="ระบุเหตุผลการยกเลิก")
        self.target_idx, self.od = target_idx, od
        self.reason = discord.ui.TextInput(label='เหตุผลที่ยกเลิก', style=discord.TextStyle.paragraph, required=True)
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
                    dr = f"{self.od['start_date']} - {self.od['end_date']}"
                    log_em.add_field(name="📅 วันที่เคยแจ้ง", value=f"{dr} `({self.od.get('total_days', 1)} วัน)`", inline=False)
                    log_em.add_field(name="🛑 เหตุผลที่ยกเลิก", value=self.reason.value, inline=False)
                    await log_ch.send(embed=log_em)
            await it.edit_original_response(content=f"✅ ยกเลิกใบลาเรียบร้อยแล้ว!", view=None)

class ConfirmCancelView(discord.ui.View):
    def __init__(self, target_idx, od):
        super().__init__(timeout=60)
        self.target_idx, self.od = target_idx, od
    @discord.ui.button(label="✅ ยืนยันการยกเลิก", style=discord.ButtonStyle.success)
    async def confirm(self, it, b):
        await it.response.send_modal(CancelReasonModal(self.target_idx, self.od))

class CancelSelect(discord.ui.Select):
    def __init__(self, opts):
        super().__init__(placeholder="📋 เลือกรายการที่จะยกเลิก...", options=opts)
    async def callback(self, it):
        await it.response.defer(ephemeral=True)
        idx = int(self.values[0])
        d = load_json(DB_LEAVE, [])
        od = d[idx]
        txt = f"⚠️ ยืนยันยกเลิกใบลาของ <@{od['target_id']}>?"
        await it.edit_original_response(content=txt, view=ConfirmCancelView(idx, od))

# --- 7. ระบบแก้ไข (ปรับปรุงตามสั่ง: Modal + Log + หัวข้อใหม่) ---
async def process_edit_leave(it, idx, od, new_end_str, edit_reason="-"):
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
                log_em = discord.Embed(title="📌 บันทึกการแก้ไขวันสิ้นสุดการลา", color=0x95a5a6)
                log_em.add_field(name="👤 สมาชิกที่ลา", value=f"<@{od['target_id']}>", inline=True)
                log_em.add_field(name="📅 วันที่ลาเดิม", value=f"{od['start_date']} - {old_e}", inline=False)
                log_em.add_field(name="📅 วันที่ลาใหม่", value=f"{od['start_date']} - {new_end_str}", inline=False)
                log_em.add_field(name="🛑 เหตุผลที่ขอแก้ไข", value=edit_reason, inline=False) # เพิ่มเหตุผลใน Log
                log_em.set_footer(text=f"บันทึกเมื่อ: {get_thai_time().strftime('%d/%m/%Y %H:%M')} น.")
                await log_ch.send(embed=log_em)
        await it.edit_original_response(content=f"✅ แก้ไขวันสิ้นสุดเรียบร้อยแล้ว!", embed=None, view=None)

class EditReasonModal(discord.ui.Modal):
    def __init__(self, idx, od, new_end):
        super().__init__(title="ระบุเหตุผลการแก้ไขวันลา")
        self.idx, self.od, self.new_end = idx, od, new_end
        self.reason = discord.ui.TextInput(label='เหตุผลที่ขอแก้ไข', style=discord.TextStyle.paragraph, required=True)
        self.add_item(self.reason)
    async def on_submit(self, it: discord.Interaction):
        await it.response.defer(ephemeral=True)
        await process_edit_leave(it, self.idx, self.od, self.new_end, self.reason.value)

class ConfirmEditView(discord.ui.View):
    def __init__(self, idx, od, new_end):
        super().__init__(timeout=60)
        self.idx, self.od, self.new_end = idx, od, new_end
    @discord.ui.button(label="✅ ยืนยันการแก้ไข", style=discord.ButtonStyle.success)
    async def confirm(self, it, b):
        await it.response.send_modal(EditReasonModal(self.idx, self.od, self.new_end)) # เด้ง Modal
    @discord.ui.button(label="📅 เลือกวันสิ้นสุดใหม่", style=discord.ButtonStyle.primary)
    async def reselect(self, it, b):
        await it.response.edit_message(content="📅 **กรุณาเลือกวันที่สิ้นสุดใหม่อีกครั้ง:**", embed=None, view=SubMenuView(it, EditDateSelect(self.idx, self.od)))
    @discord.ui.button(label="❌ ยกเลิก", style=discord.ButtonStyle.danger)
    async def cancel(self, it, b):
        await it.response.defer(); await it.delete_original_response()

class EditDateSelect(discord.ui.Select):
    def __init__(self, idx, od):
        self.idx, self.od = idx, od
        s_dt = datetime.strptime(od['start_date'], "%d/%m/%Y")
        opts = [discord.SelectOption(label=(s_dt + timedelta(days=i)).strftime("%d/%m/%Y"), value=(s_dt + timedelta(days=i)).strftime("%d/%m/%Y")) for i in range(15)]
        super().__init__(placeholder="📅 เลือกวันที่กลับมาจริง...", options=opts)
    async def callback(self, it):
        val = self.values[0]
        em = discord.Embed(title="ตรวจสอบความถูกต้องก่อนยืนยัน", color=0xffffff) # หัวข้อ + สีตามสั่ง
        em.description = (
            f"**👤 สมาชิก:** <@{self.od['target_id']}>\n"
            f"**📅 วันที่ลาเดิม:** {self.od['start_date']} - {self.od['end_date']}\n"
            f"**📅 วันที่ลาใหม่:** {self.od['start_date']} - {val}\n\n"
            f"**ยืนยันการแก้ไขข้อมูลหรือไม่?**"
        )
        await it.response.edit_message(content=None, embed=em, view=ConfirmEditView(self.idx, self.od, val))

class EditLeaveSelect(discord.ui.Select):
    def __init__(self, opts):
        super().__init__(placeholder="✏️ เลือกใบลาที่ต้องการแก้...", options=opts)
    async def callback(self, it):
        await it.response.defer(ephemeral=True)
        d = load_json(DB_LEAVE, [])
        await it.edit_original_response(content="📅 เลือกวันที่สิ้นสุดใหม่:", view=SubMenuView(it, EditDateSelect(int(self.values[0]), d[int(self.values[0])])))

# --- 8. เมนูหลักและ User Interfaces (คงเดิมจาก freshy) ---
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
        d, u_id, opts = load_json(DB_LEAVE, []), str(it.user.id), []
        for i, e in enumerate(d):
            if e['user_id'] == u_id or e['target_id'] == u_id:
                opts.append(discord.SelectOption(label=f"{e['target_id']} | {e['start_date']}", value=str(i)))
        if not opts: return await it.response.send_message("❌ ไม่พบรายการ", ephemeral=True)
        await it.response.send_message("📋 เลือกใบลา:", view=SubMenuView(it, CancelSelect(opts[:25])), ephemeral=True)
    
    @discord.ui.button(label="✏️ แก้ไขวันสิ้นสุดการลา", style=discord.ButtonStyle.secondary, custom_id="v_l_final_vMaster_DMD_master_4")
    async def l_ed(self, it, b):
        d, u_id, opts = load_json(DB_LEAVE, []), str(it.user.id), []
        for i, e in enumerate(d):
            if (e['user_id'] == u_id or e['target_id'] == u_id) and e['start_date'] != e['end_date']:
                opts.append(discord.SelectOption(label=f"{e['target_id']} | {e['start_date']}", value=str(i)))
        if not opts: return await it.response.send_message("❌ ไม่พบรายการ", ephemeral=True)
        await it.response.send_message("✏️ เลือกใบลา:", view=SubMenuView(it, EditLeaveSelect(opts[:25])), ephemeral=True)

class FriendSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="👤 เลือกเพื่อน...", min_values=1, max_values=1)
    async def callback(self, it):
        await it.response.edit_message(content=f"🎯 ลาแทนคุณ: {self.values[0].mention}", view=SubMenuView(it, DateSelect(t_id=str(self.values[0].id))))

class SubMenuView(discord.ui.View):
    def __init__(self, o_it, item=None):
        super().__init__(timeout=60)
        if item: self.add_item(item)
    @discord.ui.button(label="ปิดเมนู", style=discord.ButtonStyle.danger, row=3)
    async def cls(self, it, b):
        await it.response.defer(); await it.delete_original_response()

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