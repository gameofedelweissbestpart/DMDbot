import discord
from discord.ext import commands, tasks
import json, os, re, asyncio
from datetime import datetime, timedelta

# --- 1. การจัดการข้อมูล (คงเดิมจากไฟล์ฐาน) ---
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
        dt = datetime.strptime(d_str, "%d/%m/%Y")
        # กฎข้อที่ 1: บังคับ ค.ศ. (ปีต้องไม่เกิน 2100 เพื่อป้องกันการกรอก พ.ศ. 25xx)
        if dt.year > 2500:
            return False
        return True
    except:
        return False

# --- 2. ระบบตาราง Real-time (ปรับหัวข้อตามสั่ง) ---
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

    em = discord.Embed(color=0xf1c40f if active else 0x2ecc71)
    # ปรับหัวข้อตามสั่ง: ตัด "ของวันนี้" ออก และใช้หัวข้อนี้เสมอ
    desc = f"# 📋 รายชื่อสมาชิกที่แจ้งลา (Real-time)\n{LONG_SEP}\n\n"
    
    if not active:
        desc += "> 🍃 **ขณะนี้ยังไม่มีสมาชิกแจ้งลาในระบบ**\n\n"
    else:
        for e in active:
            # ใช้แท็กชื่อสมาชิก <@ID>
            desc += f"🔹 <@{e['target_id']}> `[{e.get('leave_category','ทั่วไป')}]`\n"
            dr = e['start_date'] if e['start_date'] == e['end_date'] else f"{e['start_date']} - {e['end_date']}"
            desc += f"└ **วันที่ลา:** {dr} `(รวม {e['total_days']} วัน)`\n"
            desc += f"└ **เหตุผลที่ลา:** {e['reason']}\n"
            if e['user_id'] != e['target_id']:
                desc += f"└ **ผู้แจ้งแทน:** <@{e['user_id']}>\n"
            desc += "\n"
        
    desc += f"{LONG_SEP}\n"
    desc += f"**📊 สรุปจำนวนคนลาวันนี้: {len(active)} คน**\n"
    desc += f"**📅 อัปเดตล่าสุด: {get_thai_time().strftime('%d/%m/%Y %H:%M น.')}**"
    em.description = desc

    target = None
    async for m in channel.history(limit=50):
        if m.author == bot.user and m.embeds and len(m.embeds) > 0:
            # ค้นหาข้อความเดิมจากหัวข้อใหม่
            if m.embeds[0].description and "รายชื่อสมาชิกที่แจ้งลา (Real-time)" in m.embeds[0].description:
                target = m
                break
    
    if target:
        await target.edit(embed=em)
    else:
        await channel.send(embed=em)

# --- 3. ระบบแจ้งลาและ Log (บังคับ ค.ศ. / ลาไม่เกิน 15 วัน / แยกสี Log) ---
class LeaveModal(discord.ui.Modal):
    def __init__(self, title, s_v, e_v, cat_val, t_id=None, is_f=False, old_re=""):
        super().__init__(title=title)
        self.t_id, self.is_f, self.cat_val = t_id, is_f, cat_val
        self.s_v, self.e_v = s_v, e_v
        
        if not is_f:
            self.s_i = discord.ui.TextInput(label='เริ่มลาวันที่ (วว/ดด/ปปปป) *ใช้ ค.ศ. เท่านั้น', placeholder='ตัวอย่าง: 25/04/2026', default=s_v, required=True)
            self.e_i = discord.ui.TextInput(label='สิ้นสุดวันที่ (วว/ดด/ปปปป) *ใช้ ค.ศ. เท่านั้น', placeholder='ตัวอย่าง: 30/04/2026', default=e_v, required=True)
            self.add_item(self.s_i)
            self.add_item(self.e_i)
        
        self.re = discord.ui.TextInput(label='เหตุผลการลา', placeholder='ระบุรายละเอียดเพิ่มเติม...', style=discord.TextStyle.paragraph, default=old_re, required=True)
        self.add_item(self.re)
    
    async def on_submit(self, it: discord.Interaction):
        # เคลียร์ Interaction เดิมเพื่อให้หน้าจอสะอาด
        s = self.s_v if self.is_f else self.s_i.value.strip()
        e = self.e_v if self.is_f else self.e_i.value.strip()
        
        # ตรวจสอบ ค.ศ.
        if not validate_date(s) or not validate_date(e):
            err_msg = f"**⚠️ รูปแบบวันที่ไม่ถูกต้อง หรือไม่ใช่ปี ค.ศ.!**\n\nท่านกรอกมาว่า: เริ่ม `{s}`, สิ้นสุด `{e}`\n(ตัวอย่าง ค.ศ. ที่ถูกต้อง: 28/04/2026) ❌"
            return await it.response.send_message(content=err_msg, view=RetryView(self.title, "", "", self.cat_val, self.t_id, self.is_f, self.re.value), ephemeral=True)
        
        today = get_thai_time().date()
        s_dt = datetime.strptime(s, "%d/%m/%Y").date()
        e_dt = datetime.strptime(e, "%d/%m/%Y").date()

        if s_dt < today:
            return await it.response.send_message(content="❌ **ไม่สามารถลาย้อนหลังได้** (กรุณาระบุวันที่ตั้งแต่วันนี้เป็นต้นไป)", view=RetryView(self.title, "", "", self.cat_val, self.t_id, self.is_f, self.re.value), ephemeral=True)
        if e_dt < s_dt:
            return await it.response.send_message(content="❌ **วันที่สิ้นสุดต้องไม่มาก่อนวันที่เริ่มต้น!**", view=RetryView(self.title, s, "", self.cat_val, self.t_id, self.is_f, self.re.value), ephemeral=True)

        # กฎข้อที่ 2: ลาได้ไม่เกิน 15 วัน
        days = (e_dt - s_dt).days + 1
        if days > 15:
            return await it.response.send_message(content=f"❌ **ไม่สามารถแจ้งลาเกิน 15 วันได้ (ท่านลา {days} วัน)**\nโปรดติดต่อแอดมินโดยตรงเพื่อทำรายการพิเศษ", view=RetryView(self.title, s, e, self.cat_val, self.t_id, self.is_f, self.re.value), ephemeral=True)

        target_uid = self.t_id if self.t_id else str(it.user.id)
        d = load_json(DB_LEAVE, [])
        
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
                # แยก Log ตามประเภท (แจ้งเองสีเขียว / แจ้งแทนเพื่อนสีฟ้า)
                is_on_behalf = True if self.t_id and self.t_id != str(it.user.id) else False
                log_title = "📌 บันทึกการแจ้งลาแทนเพื่อน" if is_on_behalf else "📌 บันทึกการแจ้งลาใหม่"
                log_color = 0x3498db if is_on_behalf else 0x2ecc71
                
                log_em = discord.Embed(title=log_title, color=log_color)
                on_behalf_txt = f"\n**👮 ผู้แจ้งลาแทน:** <@{it.user.id}>" if is_on_behalf else ""
                dr = s if s == e else f"{s} - {e}"
                
                log_em.description = (
                    f"**👤 สมาชิกที่ลา:** <@{target_uid}>{on_behalf_txt}\n\n"
                    f"**📝 ประเภท:** {self.cat_val}\n"
                    f"**📅 วันที่ลา:** {dr} `(รวม {days} วัน)`\n"
                    f"**💬 เหตุผล:** {self.re.value}\n\n"
                    f"{LONG_SEP}"
                )
                log_em.set_footer(text=f"บันทึกเมื่อ: {get_thai_time().strftime('%d/%m/%Y %H:%M')} น.")
                await log_ch.send(embed=log_em)
        
        # แก้บั๊ก: เพิ่มข้อความตอบกลับสำเร็จ และหายเองใน 3 วิ
        await it.response.send_message(content='✅ ระบบบันทึกใบลาของคุณเรียบร้อยแล้ว!', ephemeral=True)
        await asyncio.sleep(3)
        try:
            await it.delete_original_response()
        except:
            pass

class RetryView(discord.ui.View):
    def __init__(self, title, s, e, cat, t_id, is_f, re_val):
        super().__init__(timeout=120) # ค้างไว้ให้กดแก้
        self.title, self.s, self.e, self.cat, self.t_id, self.is_f, self.re_val = title, s, e, cat, t_id, is_f, re_val
    @discord.ui.button(label="📝 แก้ไขข้อมูลอีกครั้ง", style=discord.ButtonStyle.primary)
    async def retry(self, it, b):
        await it.response.send_modal(LeaveModal(self.title, self.s, self.e, self.cat, self.t_id, self.is_f, self.re_val))
        try:
            await it.delete_original_response()
        except:
            pass

# --- 4. ส่วน Admin (ปรับหัวข้อหน้าหลักตามสั่ง + หมายเหตุใหม่) ---
class ConfirmClearView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
    @discord.ui.button(label="⚠️ ยืนยันล้างข้อมูลถาวร", style=discord.ButtonStyle.danger)
    async def confirm(self, it: discord.Interaction, b):
        await it.response.defer(ephemeral=True)
        
        # กฎข้อที่ 14: ส่ง Backup เต็มรูปแบบให้แอดมินทุกคน
        admin_roles = ["Admin", "ผู้ดูแล"]
        for member in it.guild.members:
            if any(r.name in admin_roles for r in member.roles) and not member.bot:
                try:
                    f_send = []
                    if os.path.exists(DB_LEAVE): f_send.append(discord.File(DB_LEAVE))
                    if os.path.exists(CONFIG_PATH): f_send.append(discord.File(CONFIG_PATH))
                    await member.send(f"⚠️ **แจ้งเตือนการล้างข้อมูลโดย <@{it.user.id}>**\nนี่คือไฟล์สำรองข้อมูลก่อนถูกลบทิ้งครับ:", files=f_send)
                except:
                    continue

        # ล้างข้อมูลจริง
        save_json(DB_LEAVE, [])
        await update_summary_board()
        
        cfg = load_json(CONFIG_PATH, {})
        log_ch_id = cfg.get("log_ch")
        if log_ch_id:
            log_ch = bot.get_channel(int(log_ch_id))
            if log_ch:
                l_em = discord.Embed(title="⚠️ ประกาศ: มีการล้างข้อมูลใบลาทั้งหมดในระบบ", color=0xf39c12)
                l_em.description = (
                    f"**👮 ผู้ดำเนินการ:** <@{it.user.id}>\n"
                    f"**📅 วันที่ดำเนินการ:** {get_thai_time().strftime('%d/%m/%Y')}\n"
                    f"**⏰ เวลา:** {get_thai_time().strftime('%H:%M น.')}\n\n"
                    f"**📋 รายละเอียด:**\n- ทำการลบข้อมูลการลาทั้งหมดเรียบร้อยแล้ว\n- ระบบส่งไฟล์ Backup เข้า DM แอดมินทุกคนแล้ว\n\n{LONG_SEP}"
                )
                await log_ch.send(l_em)
            
        await it.edit_original_response(content="✅ ล้างข้อมูลสำเร็จและสำรองไฟล์เรียบร้อย!", view=None)
        await asyncio.sleep(3)
        try:
            await it.delete_original_response()
        except:
            pass

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
            # ปรับหัวข้อ: ใหญ่พิเศษขีดเส้นใต้ + หมายเหตุใหม่ตามสั่ง
            em = discord.Embed(
                title=None, 
                description=(
                    "# __📋 ระบบการแจ้งลาแก๊ง Dark Monday__\n"
                    "กรุณากดปุ่มด้านล่างเพื่อทำรายการที่ท่านต้องการได้เลยครับ\n\n"
                    "**⚠️ หมายเหตุสำคัญ ⚠️**\n"
                    "- การระบุวันที่ในระบบให้ใช้ปี **ค.ศ.** เท่านั้น (เช่น 28/04/2026)\n"
                    "- สมาชิกสามารถแจ้งลาได้สูงสุดไม่เกิน **15 วัน** ต่อการแจ้ง 1 ครั้ง\n"
                    "- ระบุเหตุผลการลาให้ชัดเจน (เช่น ติด OC, ธุระทางบ้าน, ลาป่วย)\n"
                    "- ระบบไม่อนุญาตให้ลาย้อนหลัง หากมีเหตุฉุกเฉินให้แจ้งแอดมินโดยตรง\n"
                    "- โปรดตรวจสอบข้อมูลให้ถูกต้อง การแจ้งลาเท็จจะมีบทลงโทษตามกฎแก๊ง"
                ), 
                color=0x3498db
            )
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
    
    # กฎข้อที่ 13: ปุ่มล้างข้อมูลทั้งหมด
    @discord.ui.button(label="🗑️ ล้างข้อมูลทั้งหมด", style=discord.ButtonStyle.danger)
    async def clear_all(self, it, b):
        txt = "⚠️ **คุณยืนยันที่จะล้างข้อมูลใบลาทั้งหมดใช่หรือไม่?**\nการกระทำนี้จะลบข้อมูลถาวรและส่งไฟล์ Backup ให้แอดมินทุกคน"
        await it.response.send_message(content=txt, view=ConfirmClearView(), ephemeral=True)

# --- 5. งานรายวัน และ รายสัปดาห์ (Auto Cleanup 30 วัน + รายสัปดาห์คลีน) ---
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
                
                # --- AUTO CLEANUP: ลบข้อมูลที่สิ้นสุดการลาเกิน 30 วัน ---
                cutoff = nd - timedelta(days=30)
                cleaned_data = []
                for e in d:
                    try:
                        e_dt = datetime.strptime(e['end_date'], "%d/%m/%Y").date()
                        if e_dt >= cutoff: cleaned_data.append(e)
                    except: cleaned_data.append(e)
                if len(cleaned_data) != len(d):
                    save_json(DB_LEAVE, cleaned_data)
                    d = cleaned_data

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
                            sn = su.display_name if su else f"ID: {i['user_id']}"
                            msg += f" **(แจ้งแทนโดย: {sn})**"
                        msg += "\n"
                    
                    summary_msg = "\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n**📊 สรุปยอดรวม:**\n"
                    for cat_name, count in counts.items():
                        summary_msg += f"• {cat_name} : {count} คน\n"
                    summary_msg += f"**👥 รวมสมาชิกที่ลาทั้งหมด {len(ac)} คน**\n\u200b"
                    em.description = msg + summary_msg
                
                em.set_footer(text=f"บันทึกเมื่อ: {n.strftime('%H:%M')} น.")
                await ch.send(embed=em)

    # รายสัปดาห์ ทุกวันจันทร์ 00:10 น. (กรอง Role 2 ชั้น + ชื่อคลีนเพียวๆ)
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
                
                d = load_json(DB_LEAVE, [])
                end_range = n.date() - timedelta(days=1)
                start_range = end_range - timedelta(days=6)
                
                user_stats = {}
                for m in valid_members:
                    user_stats[str(m.id)] = {'leaves': 0, 'days': 0, 'member': m}

                for e in d:
                    t_id = e['target_id']
                    if t_id in user_stats:
                        try:
                            s_d = datetime.strptime(e['start_date'], "%d/%m/%Y").date()
                            e_d = datetime.strptime(e['end_date'], "%d/%m/%Y").date()
                            overlap_start = max(s_d, start_range)
                            overlap_end = min(e_d, end_range)
                            if overlap_start <= overlap_end:
                                days = (overlap_end - overlap_start).days + 1
                                user_stats[t_id]['leaves'] += 1
                                user_stats[t_id]['days'] += days
                        except: continue

                em = discord.Embed(title="📊 สรุปรายชื่อการแจ้งลาประจำสัปดาห์", color=0x2b2d31)
                left_list = [v for k, v in user_stats.items() if v['leaves'] > 0]
                ready_list = [v for k, v in user_stats.items() if v['leaves'] == 0]
                
                msg_left = "```\n"
                if not left_list: msg_left += "ไม่มีรายชื่อ\n"
                else:
                    for s in sorted(left_list, key=lambda x: x['leaves'], reverse=True):
                        msg_left += f"{s['member'].display_name}\n"
                msg_left += "```"

                msg_ready = "```\n"
                if not ready_list: msg_ready += "ไม่มีรายชื่อ\n"
                else:
                    for s in ready_list:
                        msg_ready += f"{s['member'].display_name}\n"
                msg_ready += "```"
                
                em.add_field(name="✅ สมาชิกที่แจ้งลา", value=msg_left, inline=False)
                em.add_field(name="❌ สมาชิกที่ไม่ได้แจ้งลา", value=msg_ready, inline=False)
                em.set_footer(text=f"บันทึกเมื่อ: {n.strftime('%d/%m/%Y %H:%M น.')}")
                await w_ch.send(embed=em)

# --- 6. ระบบยกเลิกใบลา (ปรับหัวข้อ Log และลบบรรทัดสถานะออก) ---
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
                    
                    # กฎข้อที่ 11: เช็กชื่อผู้ยกเลิกแทนจากเจ้าของใบลา
                    is_on_behalf = str(it.user.id) != self.od['target_id']
                    on_behalf = f"\n**👮 ผู้ยกเลิกแทน:** <@{it.user.id}>" if is_on_behalf else ""
                    dr = self.od['start_date'] if self.od['start_date'] == self.od['end_date'] else f"{self.od['start_date']} - {self.od['end_date']}"
                    
                    # ปรับ Log: ใช้ "วันที่ลา" และลบบรรทัดสถานะ
                    log_em.description = (
                        f"**👤 สมาชิกที่ลา:** <@{self.od['target_id']}>{on_behalf}\n\n"
                        f"**📝 ประเภท:** {self.od.get('leave_category', 'ทั่วไป')}\n"
                        f"**📅 วันที่ลา:** {dr} `(รวม {self.od.get('total_days', 1)} วัน)`\n"
                        f"**💬 เหตุผลเดิมที่แจ้ง:** {self.od.get('reason', '-')}\n"
                        f"**🛑 เหตุผลที่ยกเลิก:** {self.reason.value}\n\n"
                        f"{LONG_SEP}"
                    )
                    log_em.set_footer(text=f"บันทึกเมื่อ: {get_thai_time().strftime('%d/%m/%Y %H:%M')} น.")
                    await log_ch.send(embed=log_em)
            
            await it.edit_original_response(content=f"❌ ยกเลิกรายการแจ้งลาเรียบร้อยแล้ว!", view=None)
        await asyncio.sleep(3)
        try:
            await it.delete_original_response()
        except:
            pass

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
        try:
            await it.delete_original_response()
        except:
            pass

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
            txt = f"⚠️ **แน่ใจหรือไม่ที่จะยกเลิกการลานี้?**\n👤 **คนลา:** <@{od['target_id']}>\n📝 **ประเภท:** `{od.get('leave_category','ทั่วไป')}`\n📅 **วันที่:** {dr} `({od.get('total_days', 1)} วัน)`"
            await it.edit_original_response(content=txt, view=ConfirmCancelView(idx, od))

# --- 7. ระบบแก้ไขวันสิ้นสุด (เอาตัวเลือกพิมพ์วันที่เองออก และจำกัด 15 วัน) ---
async def process_edit_leave(it, idx, od, new_end_str):
    d = load_json(DB_LEAVE, [])
    old_e = od['end_date']
    if 0 <= idx < len(d):
        old_days = (datetime.strptime(old_e, "%d/%m/%Y") - datetime.strptime(od['start_date'], "%d/%m/%Y")).days + 1
        new_days = (datetime.strptime(new_end_str, "%d/%m/%Y") - datetime.strptime(od['start_date'], "%d/%m/%Y")).days + 1
        diff = new_days - old_days
        diff_txt = f"เพิ่มขึ้น {diff} วัน" if diff > 0 else f"ลดลง {abs(diff)} วัน" if diff < 0 else "จำนวนวันเท่าเดิม"

        d[idx]['end_date'] = new_end_str
        d[idx]['total_days'] = new_days
        save_json(DB_LEAVE, d)
        await update_summary_board()
        
        cfg = load_json(CONFIG_PATH, {})
        log_ch_id = cfg.get("log_ch")
        if log_ch_id:
            log_ch = bot.get_channel(int(log_ch_id))
            if log_ch:
                log_em = discord.Embed(title="📌 บันทึกการแก้ไขวันสิ้นสุดการลา", color=0x95a5a6)
                on_behalf = f"\n**👮 ผู้แจ้งแก้ไขแทน:** <@{it.user.id}>" if od['target_id'] != str(it.user.id) else ""
                
                log_em.description = (
                    f"**👤 สมาชิกที่ลา:** <@{od['target_id']}>{on_behalf}\n\n"
                    f"**📝 ประเภท:** {od.get('leave_category', 'ทั่วไป')}\n"
                    f"**📅 วันที่ลาเดิม:** {od['start_date']} - {old_e} `(รวม {old_days} วัน)`\n"
                    f"**🔹 วันที่ลาใหม่:** {od['start_date']} - {new_end_str} `(รวม {new_days} วัน)`\n"
                    f"**📈 การเปลี่ยนแปลง:** `{diff_txt}`\n"
                    f"**💬 เหตุผลเดิมที่แจ้ง:** {od.get('reason', '-')}\n\n"
                    f"{LONG_SEP}"
                )
                log_em.set_footer(text=f"บันทึกเมื่อ: {get_thai_time().strftime('%d/%m/%Y %H:%M')} น.")
                await log_ch.send(embed=log_em)
        
        await it.edit_original_response(content=f"✏️ แก้ไขข้อมูลการลาเรียบร้อยแล้ว!", embed=None, view=None)
        await asyncio.sleep(3)
        try:
            await it.delete_original_response()
        except:
            pass

class EditRetryView(discord.ui.View):
    def __init__(self, idx, od, p_it):
        super().__init__(timeout=120)
        self.idx, self.od, self.p_it = idx, od, p_it
    @discord.ui.button(label="📝 แก้ไขวันที่อีกครั้ง", style=discord.ButtonStyle.primary)
    async def retry(self, it, b):
        await it.response.edit_message(content="📅 **เลือกวันที่สิ้นสุดใหม่อีกครั้ง:**", embed=None, view=SubMenuView(it, EditDateSelect(self.idx, self.od, it)))
        try:
            await it.delete_original_response()
        except:
            pass

class EditDateModal(discord.ui.Modal):
    def __init__(self, idx, od, parent_it=None):
        super().__init__(title="ระบุวันที่กลับมาจริง")
        self.idx, self.od, self.parent_it = idx, od, parent_it
        self.new_e = discord.ui.TextInput(label='วันที่กลับมาจริง (วว/ดด/ปปปป) *ใช้ ค.ศ. เท่านั้น', placeholder='ตัวอย่าง: 28/04/2026', required=True)
        self.add_item(self.new_e)
    async def on_submit(self, it: discord.Interaction):
        val = self.new_e.value.strip()
        if not validate_date(val):
            return await it.response.send_message("❌ รูปแบบวันที่ไม่ถูกต้อง หรือไม่ใช่ปี ค.ศ.!", view=EditRetryView(self.idx, self.od, self.parent_it), ephemeral=True)
        s_dt = datetime.strptime(self.od['start_date'], "%d/%m/%Y")
        e_dt = datetime.strptime(val, "%d/%m/%Y")
        if e_dt < s_dt:
            return await it.response.send_message("❌ วันที่กลับมาจริงต้องไม่มาก่อนวันที่เริ่มลา!", view=EditRetryView(self.idx, self.od, self.parent_it), ephemeral=True)
        new_days = (e_dt - s_dt).days + 1
        if new_days > 15:
            return await it.response.send_message(content=f"❌ **ไม่สามารถลาเกิน 15 วันได้ (ยอดใหม่คือ {new_days} วัน)**\nโปรดติดต่อแอดมินเพื่อแก้ไขรายการนี้", view=EditRetryView(self.idx, self.od, self.parent_it), ephemeral=True)
        if self.parent_it:
            try: await self.parent_it.delete_original_response()
            except: pass
        old_days = (datetime.strptime(self.od['end_date'], "%d/%m/%Y") - s_dt).days + 1
        diff = new_days - old_days
        diff_txt = f"เพิ่มขึ้น {diff} วัน" if diff > 0 else f"ลดลง {abs(diff)} วัน" if diff < 0 else "จำนวนวันเท่าเดิม"
        em = discord.Embed(title="確認 | ตรวจสอบความถูกต้อง", color=0xffffff)
        em.description = (
            f"**👤 สมาชิก:** <@{self.od['target_id']}>\n"
            f"**📅 วันที่ลาเดิม:** {self.od['start_date']} - {self.od['end_date']} `({old_days} วัน)`\n"
            f"**🔹 วันที่ลาใหม่:** {self.od['start_date']} - {val} `({new_days} วัน)`\n"
            f"**📊 การเปลี่ยนแปลง:** `{diff_txt}`\n\n"
            f"**ยืนยันการแก้ไขข้อมูลหรือไม่?**"
        )
        await it.response.send_message(embed=em, view=ConfirmEditView(self.idx, self.od, val), ephemeral=True)

class ConfirmEditView(discord.ui.View):
    def __init__(self, idx, od, new_end):
        super().__init__(timeout=60)
        self.idx, self.od, self.new_end = idx, od, new_end
    @discord.ui.button(label="✅ ยืนยันการแก้ไข", style=discord.ButtonStyle.success)
    async def confirm(self, it, b):
        await it.response.defer(ephemeral=True)
        await process_edit_leave(it, self.idx, self.od, self.new_end)
    @discord.ui.button(label="📅 เลือกวันใหม่", style=discord.ButtonStyle.primary)
    async def reselect(self, it, b):
        await it.response.edit_message(content="📅 **กรุณาเลือกวันที่สิ้นสุดใหม่อีกครั้ง:**", embed=None, view=SubMenuView(it, EditDateSelect(self.idx, self.od, it)))
    @discord.ui.button(label="❌ ยกเลิก", style=discord.ButtonStyle.danger)
    async def cancel(self, it, b):
        await it.response.defer()
        try:
            await it.delete_original_response()
        except:
            pass

class EditDateSelect(discord.ui.Select):
    def __init__(self, idx, od, parent_it=None):
        self.idx, self.od, self.parent_it = idx, od, parent_it
        s_dt = datetime.strptime(od['start_date'], "%d/%m/%Y")
        opts = []
        # ปรับแก้ไข: ให้เลือกได้ 15 วันนับจากวันเริ่มลา (ไม่เกินกฎ 15 วัน)
        for i in range(15):
            d_str = (s_dt + timedelta(days=i)).strftime("%d/%m/%Y")
            opts.append(discord.SelectOption(label=d_str, value=d_str))
        
        # เอาส่วน "ระบุวันที่เอง" ออกตามตกลง
        super().__init__(placeholder="📅 เลือกวันที่กลับมาจริง...", options=opts)
    
    async def callback(self, it: discord.Interaction):
        val = self.values[0]
        s_dt = datetime.strptime(self.od['start_date'], "%d/%m/%Y")
        e_dt = datetime.strptime(val, "%d/%m/%Y")
        new_days = (e_dt - s_dt).days + 1
        old_days = (datetime.strptime(self.od['end_date'], "%d/%m/%Y") - s_dt).days + 1
        diff = new_days - old_days
        diff_txt = f"เพิ่มขึ้น {diff} วัน" if diff > 0 else f"ลดลง {abs(diff)} วัน" if diff < 0 else "จำนวนวันเท่าเดิม"

        em = discord.Embed(title="確認 | ตรวจสอบความถูกต้อง", color=0xffffff)
        em.description = (
            f"**👤 สมาชิก:** <@{self.od['target_id']}>\n"
            f"**📅 วันที่ลาเดิม:** {self.od['start_date']} - {self.od['end_date']} `({old_days} วัน)`\n"
            f"**🔹 วันที่ลาใหม่:** {self.od['start_date']} - {val} `({new_days} วัน)`\n"
            f"**📊 การเปลี่ยนแปลง:** `{diff_txt}`\n\n"
            f"**ยืนยันการแก้ไขข้อมูลหรือไม่?**"
        )
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

# --- 8. เมนูหลัก 4 ปุ่ม (คงเดิมทุกลิงก์ custom_id + เพิ่มสิทธิ์แอดมิน) ---
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
        # กฎข้อที่ 10: สิทธิ์แอดมินสามารถเห็นและยกเลิกของทุกคนได้
        is_admin = any(r.name in ["Admin", "ผู้ดูแล"] for r in it.user.roles)
        
        for i, e in enumerate(d):
            if is_admin or e['user_id'] == u_id or e['target_id'] == u_id:
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
        if not opts: return await it.response.send_message("❌ ไม่พบรายการที่จะยกเลิก", ephemeral=True)
        await it.response.send_message("📋 เลือกใบลาที่จะยกเลิก:", view=SubMenuView(it, CancelSelect(opts[:25])), ephemeral=True)
    
    @discord.ui.button(label="✏️ แก้ไขวันสิ้นสุดการลา", style=discord.ButtonStyle.secondary, custom_id="v_l_final_vMaster_DMD_master_4")
    async def l_ed(self, it, b):
        d = load_json(DB_LEAVE, [])
        u_id, now_date, opts = str(it.user.id), get_thai_time().date(), []
        is_admin = any(r.name in ["Admin", "ผู้ดูแล"] for r in it.user.roles)

        for i, e in enumerate(d):
            if (is_admin or e['user_id'] == u_id or e['target_id'] == u_id) and e['start_date'] != e['end_date']:
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
        if not opts: return await it.response.send_message("❌ ไม่พบรายการที่สามารถแก้ไขได้ (ต้องเป็นการลาหลายวัน)", ephemeral=True)
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
        try:
            await it.delete_original_response()
        except:
            pass

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
        try:
            await it.delete_original_response()
        except:
            pass

@bot.command()
@commands.has_any_role("Admin", "ผู้ดูแล")
async def admin(ctx):
    await ctx.send(embed=discord.Embed(title="🕹 Dark Monday Admin Panel"), view=AdminPanelView())

# --- 9. ระบบ Backup (ส่งข้อมูล 2 ไฟล์ให้แอดมินทุกคน) ---
@bot.command()
@commands.has_any_role("Admin", "ผู้ดูแล")
async def backup(ctx):
    admin_roles = ["Admin", "ผู้ดูแล"]
    count = 0
    for member in ctx.guild.members:
        if any(r.name in admin_roles for r in member.roles) and not member.bot:
            try:
                f_send = []
                if os.path.exists(DB_LEAVE): f_send.append(discord.File(DB_LEAVE))
                if os.path.exists(CONFIG_PATH): f_send.append(discord.File(CONFIG_PATH))
                await member.send("📦 นี่คือไฟล์ Backup ข้อมูลและการตั้งค่าระบบครับ:", files=f_send)
                count += 1
            except:
                continue
    await ctx.send(f"✅ ส่งไฟล์ Backup เข้า DM ของแอดมินทั้งหมด {count} ท่านเรียบร้อยแล้ว")

@bot.event
async def on_ready():
    bot.add_view(LeaveMainView())
    print('Bot DMD Online | System Year: 2026')
    if not daily_report_task.is_running(): daily_report_task.start()

bot.run(TOKEN)