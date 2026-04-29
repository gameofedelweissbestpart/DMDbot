import discord
from discord.ext import commands, tasks
import json, os, re, asyncio, shutil
from datetime import datetime, timedelta

# --- 1. การจัดการข้อมูล (คงเดิมจากไฟล์ฐาน) ---
TOKEN = os.getenv('DISCORD_TOKEN')
CONFIG_PATH = '/app/data/config.json'
DB_LEAVE = '/app/data/gang_leaves.json'
FINE_DATA_PATH = '/app/data/fine_data.json'       # <--- เพิ่ม
FINE_HISTORY_PATH = '/app/data/fine_history.json'  # <--- เพิ่ม
BACKUP_PATH = '/app/data/fine_data.json.bak'       # <--- เพิ่ม
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

# --- ฟังก์ชันจัดการข้อมูลค่าปรับและ Backup อัตโนมัติ ---
def load_fines():
    # ดึงข้อมูลยอดหนี้สะสม และประวัติ
    return load_json(FINE_DATA_PATH, {"unpaid_fines": {}, "history": {}})

def save_fines(data):
    # บันทึกข้อมูลและทำ Backup ทันที
    save_json(FINE_DATA_PATH, data)
    if os.path.exists(FINE_DATA_PATH):
        shutil.copyfile(FINE_DATA_PATH, BACKUP_PATH)

# --- ระบบส่ง Log (ชิดซ้ายสุด / ▫️ / ไม่มี :) ---
async def send_fine_log(guild, title, description, admin_name=None):
    conf = load_json(CONFIG_PATH, {})
    log_ch_id = conf.get('fine_log_ch') # ดึง ID ห้อง Log การปรับเงิน
    if not log_ch_id: return
    channel = guild.get_channel(int(log_ch_id))
    if not channel: return

    admin_info = f"**👤 แอดมินผู้ดำเนินการ:** `{admin_name}`\n" if admin_name else ""
    
    # สร้าง Embed สไตล์ที่คุณต้องการเป๊ะๆ
    embed = discord.Embed(
        description=f"**📌{title}**\n"
                    f"{admin_info}"
                    f"{description}\n"
                    f"{LONG_SEP}",
        color=0x2f3136
    )
    embed.set_footer(text=f"🕒 บันทึกเมื่อ: {get_thai_time().strftime('%d/%m/%Y | %H:%M:%S น.')}")
    await channel.send(embed=embed)
        
#รีเฟรช refresh
class RealtimeRefreshView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔄 กดอัปเดตข้อมูลล่าสุด", style=discord.ButtonStyle.success, custom_id="refresh_realtime_board")
    async def refresh_board(self, it: discord.Interaction, b: discord.ui.Button):
        await it.response.send_message("🔄 กำลังอัปเดตข้อมูลบนบอร์ด...", ephemeral=True) # 1. จองคิวการตอบกลับแบบเห็นคนเดียว
        await update_summary_board() # เรียกตัวเองเพื่ออัปเดตข้อมูล
        await it.edit_original_response(content="✅ อัปเดตข้อมูลบนบอร์ดให้เป็นล่าสุดเรียบร้อยแล้ว!")
        await asyncio.sleep(3) # รอ 3 วินาทีแล้วสั่งทำลายข้อความลับนั้นทิ้ง
        await it.delete_original_response()

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

    # ปรับหัวข้อตามสั่ง: ตัด "ของวันนี้" ออก และใช้หัวข้อนี้เสมอ
    desc = f"# 📋 รายชื่อสมาชิกที่แจ้งลา (Real-time)\n{LONG_SEP}\n\n"
    em = discord.Embed(description=desc, color=0x2B2D31)
    
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
        await target.edit(embed=em, view=RealtimeRefreshView()) # ใส่ปุ่มเข้าไป
    else:
        await channel.send(embed=em, view=RealtimeRefreshView()) # ใส่ปุ่มเข้าไป

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
                await log_ch.send(embed=l_em)
            
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
                color=0x2B2D31
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
            discord.SelectOption(label="📊 สรุปประวัติรายสัปดาห์", value="weekly_ch"),
            discord.SelectOption(label="💰 ห้องแจ้งยอดค่าปรับ", value="fine_ch"),
            discord.SelectOption(label="🧾 ห้องตรวจสลิป/ใบเสร็จ", value="payment_log_ch")
        ]
        await it.response.send_message("🛠 เลือกหัวข้อที่ต้องการตั้งค่า:", view=SubMenuView(it, AdminCatSelect(opts)), ephemeral=True)
    
    # กฎข้อที่ 13: ปุ่มล้างข้อมูลทั้งหมด
    @discord.ui.button(label="🗑️ ล้างข้อมูลทั้งหมด", style=discord.ButtonStyle.danger)
    async def clear_all(self, it, b):
        txt = "⚠️ **คุณยืนยันที่จะล้างข้อมูลใบลาทั้งหมดใช่หรือไม่?**\nการกระทำนี้จะลบข้อมูลถาวรและส่งไฟล์ Backup ให้แอดมินทุกคน"
        await it.response.send_message(content=txt, view=ConfirmClearView(), ephemeral=True)

    @discord.ui.button(label="💰 จัดการเช็กชื่อ & ค่าปรับ", style=discord.ButtonStyle.success)
    async def manage_fines(self, it: discord.Interaction, b: discord.ui.Button):
        # 1. ต้องใส่ defer เพื่อไม่ให้ขึ้น "โต้ตอบล้มเหลว"
        await it.response.defer(ephemeral=True) 
        
        # 2. ดึงรายชื่อสมาชิก
        members = get_gang_members(it.guild)
        if not members: 
            return await it.followup.send("❌ ไม่พบสมาชิกมียศที่กำหนด", ephemeral=True)
            
        # 3. ต้องใช้ followup.send เพื่อส่งเมนูเช็กชื่อแบบ 2 กลุ่มที่เราเพิ่งวางไปท้ายไฟล์
        await it.followup.send(
            "🛠 **เมนูแอดมิน:** เลือกสมาชิกเพื่อเช็กกิจกรรมย้อนหลัง (แบ่ง 2 กลุ่ม)", 
            view=AttendanceView(members), 
            ephemeral=True
        )

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
                yesterday = n - timedelta(days=1)
                nd = yesterday.date()
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
                    except:
                        continue
                
                # --- ส่วนที่ปรับปรุงดีไซน์ตามที่คุณสั่ง ---
                separator = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
                
                em = discord.Embed(
                    title=f"**📋 __รายงานสรุปการลาประจำวัน__**",
                    description=f"**📅 ของวันที่ {yesterday.strftime('%d/%m/%Y')}**\n{separator}",
                    color=0x2B2D31 if ac else 0x2ecc71
                )

                if not ac:
                    em.description += f"\n\n✨ **วันนี้สมาชิก DMD ทุกคนอยู่ครบ!**\n✅ พร้อมรันทุกกิจกรรม ไม่มีใครแจ้งลา\n\n{separator}"
                else:
                    msg = ""
                    for i in ac:
                        tg = ch.guild.get_member(int(i['target_id']))
                        tn = tg.display_name if tg else f"ID: {i['target_id']}"
                        cat = i.get('leave_category', 'ทั่วไป')
                        
                        # แสดงผล: 👤 ชื่อ — [ประเภท]
                        msg += f"👤 **{tn}** — ` {cat} `\n"
                        # แสดงผล: ┗ 💬 เหตุผล
                        msg += f"┗ เหตุผล: {i['reason']}"
                        
                        if i['user_id'] != i['target_id']:
                            su = ch.guild.get_member(int(i['user_id']))
                            sn = su.display_name if su else f"ID: {i['user_id']}"
                            msg += f" *(ผู้ลาแทน: {sn})*"
                        msg += "\n\n"
                    
                    # รายชื่อคนลา
                    em.add_field(name="\u200b", value=msg, inline=False)
                    
                    # ส่วนสรุปยอดรวม (อยู่ล่างเส้นคั่น)
                    summary_msg = f"{separator}\n"
                    summary_msg += f"📊 **สรุปยอดรวมทั้งหมด: {len(ac)} คน**\n"
                    for cat_name, count in counts.items():
                        summary_msg += f"• {cat_name}: `{count}` คน\n"
                    
                    em.add_field(name="\u200b", value=summary_msg, inline=False)

                em.set_footer(text=f"ระบบรายงานอัตโนมัติ: {get_thai_time().strftime('%d/%m/%Y %H:%M')} น.")
                await ch.send(embed=em)

    # --- ฟังก์ชันสรุปรายสัปดาห์ (วางต่อจาก daily_report_task หรือก่อน bot.run) ---
@tasks.loop(minutes=1)
async def weekly_report_task():
    n = get_thai_time()
    
    # ตั้งค่าให้ส่งทุกวันจันทร์ (weekday == 0) เวลา 00:10 น.
    if n.weekday() == 0 and n.hour == 0 and n.minute == 10:
        cfg = load_json(CONFIG_PATH, {})
        ch_id = cfg.get("daily_ch", 0) # ใช้ช่องเดียวกับสรุปรายวัน หรือเปลี่ยนตามต้องการ
        
        if ch_id:
            ch = bot.get_channel(int(ch_id))
            guild = ch.guild if ch else None
            if ch and guild:
                # 1. ดึงข้อมูลและกำหนดช่วงวันที่ (ย้อนหลัง 7 วัน)
                all_data = load_json(DB_LEAVE, [])
                start_week = (n - timedelta(days=7)).date()
                end_week = (n - timedelta(days=1)).date()
                
                # 2. กรองสมาชิกตาม Role
                target_role_id = 1456228588968739028
                exclude_role_id = 1498319593939144755
                
                gang_members = []
                for m in guild.members:
                    has_target = any(r.id == target_role_id for r in m.roles)
                    has_exclude = any(r.id == exclude_role_id for r in m.roles)
                    if has_target and not has_exclude:
                        gang_members.append(m)

                # 3. คำนวณการลา
                leave_stats = {} # {user_id: count}
                cat_counts = {}  # {category: count}
                for entry in all_data:
                    try:
                        s_d = datetime.strptime(entry['start_date'], "%d/%m/%Y").date()
                        e_d = datetime.strptime(entry['end_date'], "%d/%m/%Y").date()
                        # เช็คว่าช่วงที่ลา คาบเกี่ยวกับสัปดาห์ที่ผ่านมาหรือไม่
                        if not (e_d < start_week or s_d > end_week):
                            uid = entry['target_id']
                            # นับจำนวนวันลาที่อยู่ในสัปดาห์นี้
                            overlap_s = max(s_d, start_week)
                            overlap_e = min(e_d, end_week)
                            days = (overlap_e - overlap_s).days + 1
                            
                            leave_stats[uid] = leave_stats.get(uid, 0) + days
                            cat = entry.get('leave_category', 'ทั่วไป')
                            cat_counts[cat] = cat_counts.get(cat, 0) + 1
                    except: continue

                # 4. แยกกลุ่มสมาชิก
                away_list = []
                active_list = []
                for m in gang_members:
                    uid_str = str(m.id)
                    if uid_str in leave_stats:
                        away_list.append(f"👤 **{m.display_name}** — `{leave_stats[uid_str]}` วัน")
                    else:
                        active_list.append(f"👤 **{m.display_name}**")

                # 5. สร้าง Embed
                separator = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
                em = discord.Embed(
                    title="📊 รายงานสรุปการลาประจำสัปดาห์",
                    description=f"**ช่วงวันที่ {start_week.strftime('%d/%m/%Y')} - {end_week.strftime('%d/%m/%Y')}**\n{separator}",
                    color=0x2B2D31
                )

                # รายชื่อคนลา
                away_text = "\n".join(away_list) if away_list else "ไม่มีสมาชิกแจ้งลา"
                em.add_field(name=f"❌ สมาชิกที่แจ้งลา (สัปดาห์นี้)", value=f"{away_text}\n*(รวม: {len(away_list)} คน)*", inline=False)

                # รายชื่อคน Active (เรียงลงล่าง)
                # หมายเหตุ: หากชื่อยาวเกิน 1024 ตัวอักษร Discord จะตัดทิ้ง ในกรณีสมาชิก 30 คนมักจะไม่มีปัญหา
                active_text = "\n".join(active_list) if active_list else "ไม่มีสมาชิก Active"
                em.add_field(name=f"✅ สมาชิกที่ไม่ได้ลาเลย (Active)", value=f"{active_text}\n*(รวม: {len(active_list)} คน)*", inline=False)

                # สรุปท้าย
                total_m = len(gang_members)
                active_percent = (len(active_list) / total_m * 100) if total_m > 0 else 0
                
                summary_msg = f"{separator}\n📊 **สรุปยอดรวมทั้งหมด: {total_m} คน**\n"
                for c_name, c_num in cat_counts.items():
                    summary_msg += f"• {c_name}: `{c_num}` ครั้ง\n"
                
                # สถิติและ % ความแอคทีฟ
                if cat_counts:
                    top_cat = max(cat_counts, key=cat_counts.get)
                    summary_msg += f"\n📈 **สถิติ:** สัปดาห์นี้สมาชิกลา **\"{top_cat}\"** มากที่สุด"
                
                summary_msg += f"\n✨ **ความแอคทีฟสัปดาห์นี้: {active_percent:.1f}%**"
                
                em.add_field(name="\u200b", value=summary_msg, inline=False)
                em.set_footer(text=f"ระบบรายงานอัตโนมัติ • {n.strftime('%d/%m/%Y %H:%M น.')}")

                await ch.send(embed=em)

# --- อย่าลืมเพิ่มการสั่งรัน Task ใน on_ready ---
# ในฟังก์ชัน on_ready() ของคุณ ให้เพิ่มบรรทัดนี้:
# if not weekly_report_task.is_running():
#     weekly_report_task.start()

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

# --- 7. ระบบแก้ไขวันสิ้นสุด (ปรับตามสั่ง: ตัดพิมพ์เอง / หัวข้อใหม่ / อีโมจิปฏิทิน / Modal เหตุผล) ---
async def process_edit_leave(it, idx, od, new_end_str, edit_reason="-"):
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
                    f"**📅 วันที่ลาใหม่:** {od['start_date']} - {new_end_str} `(รวม {new_days} วัน)`\n"
                    f"**📈 การเปลี่ยนแปลง:** `{diff_txt}`\n"
                    f"**💬 เหตุผลเดิมที่แจ้ง:** {od.get('reason', '-')}\n"
                    f"**🛑 เหตุผลที่ขอแก้ไข:** {edit_reason}\n\n"
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

class EditReasonModal(discord.ui.Modal):
    def __init__(self, idx, od, new_end):
        super().__init__(title="ระบุเหตุผลการแก้ไขวันลา")
        self.idx, self.od, self.new_end = idx, od, new_end
        self.reason = discord.ui.TextInput(label='เหตุผลที่ขอแก้ไข', placeholder='ระบุรายละเอียด...', style=discord.TextStyle.paragraph, required=True)
        self.add_item(self.reason)
    async def on_submit(self, it: discord.Interaction):
        await it.response.defer(ephemeral=True)
        await process_edit_leave(it, self.idx, self.od, self.new_end, self.reason.value)

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
        em = discord.Embed(title="ตรวจสอบความถูกต้องก่อนยืนยัน", color=0xffffff)
        em.description = (
            f"**👤 สมาชิก:** <@{self.od['target_id']}>\n"
            f"**📅 วันที่ลาเดิม:** {self.od['start_date']} - {self.od['end_date']} `({old_days} วัน)`\n"
            f"**📅 วันที่ลาใหม่:** {self.od['start_date']} - {val} `({new_days} วัน)`\n"
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
        # เรียก Modal เพื่อขอเหตุผลก่อนบันทึก
        await it.response.send_modal(EditReasonModal(self.idx, self.od, self.new_end))
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
        for i in range(15):
            d_str = (s_dt + timedelta(days=i)).strftime("%d/%m/%Y")
            opts.append(discord.SelectOption(label=d_str, value=d_str))
        super().__init__(placeholder="📅 เลือกวันที่กลับมาจริง...", options=opts)
    async def callback(self, it: discord.Interaction):
        val = self.values[0]
        s_dt = datetime.strptime(self.od['start_date'], "%d/%m/%Y")
        e_dt = datetime.strptime(val, "%d/%m/%Y")
        new_days = (e_dt - s_dt).days + 1
        old_days = (datetime.strptime(self.od['end_date'], "%d/%m/%Y") - s_dt).days + 1
        diff = new_days - old_days
        diff_txt = f"เพิ่มขึ้น {diff} วัน" if diff > 0 else f"ลดลง {abs(diff)} วัน" if diff < 0 else "จำนวนวันเท่าเดิม"

        em = discord.Embed(title="ตรวจสอบความถูกต้องก่อนยืนยัน", color=0xffffff)
        em.description = (
            f"**👤 สมาชิก:** <@{self.od['target_id']}>\n"
            f"**📅 วันที่ลาเดิม:** {self.od['start_date']} - {self.od['end_date']} `({old_days} วัน)`\n"
            f"**📅 วันที่ลาใหม่:** {self.od['start_date']} - {val} `({new_days} วัน)`\n"
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
        await it.response.edit_message(content=f"✅ เลือกช่วงเวลา: **{title}**\n👉 กรุณาเลือกประเภทการลาด้านล่าง:", view=SubMenuView(it, LeaveCategorySelect(title, s, e, self.t_id, is_f=is_fixed)))

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


# ==========================================
# ส่วนที่เพิ่มใหม่: ระบบจัดการค่าปรับและอนุมัติหลักฐาน (DMD)
# ==========================================

FINE_DB = '/app/data/fines.json'

def load_fines():
    return load_json(FINE_DB, {"unpaid_fines": {}, "payment_history": []})

def save_fines(data):
    save_json(FINE_DB, data)

def get_gang_members(guild):
    target_role_id = 1456228588968739028
    exclude_role_id = 1498319593939144755
    members = []
    if not guild: return []
    for m in guild.members:
        role_ids = [r.id for r in m.roles]
        if target_role_id in role_ids and exclude_role_id not in role_ids:
            members.append(m)
    return members[:30]

class RejectReasonModal(discord.ui.Modal, title='ระบุเหตุผลการปฏิเสธ'):
    reason = discord.ui.TextInput(label='เหตุผลที่ไม่ผ่าน', placeholder='เช่น รูปไม่ชัดเจน, ยอดเงินไม่ครบ...', style=discord.TextStyle.paragraph, required=True)
    def __init__(self, target_member, admin_name):
        super().__init__()
        self.target_member = target_member
        self.admin_name = admin_name

    async def on_submit(self, it: discord.Interaction):
        await it.response.defer(ephemeral=True)
        try:
            msg = f"⚠️ **การแจ้งชำระค่าปรับของคุณไม่ผ่าน**\n**เหตุผล:** {self.reason.value}\n**โดยแอดมิน:** {self.admin_name}\n📌 กรุณาส่งหลักฐานใหม่อีกครั้งครับ"
            await self.target_member.send(msg)
            await it.followup.send(f"✅ ส่งเหตุผลให้ {self.target_member.display_name} แล้ว", ephemeral=True)
        except:
            await it.followup.send(f"❌ สมาชิกปิด DM", ephemeral=True)

class AdminVerifyView(discord.ui.View):
    def __init__(self, member_id, amount):
        super().__init__(timeout=None)
        self.member_id = member_id
        self.amount = amount

    @discord.ui.button(label="✅ อนุมัติ", style=discord.ButtonStyle.success, custom_id="approve_fine_btn")
    async def approve(self, it: discord.Interaction, b):
        await it.response.defer(ephemeral=True)
        f_data = load_fines()
        uid = str(self.member_id)
        if uid in f_data["unpaid_fines"]:
            del f_data["unpaid_fines"][uid]
            f_data["payment_history"].append({"user_id": uid, "admin": it.user.display_name, "date": get_thai_time().strftime("%d/%m/%Y %H:%M")})
            save_fines(f_data)
            await it.edit_original_response(content="✅ อนุมัติเรียบร้อย", view=None)
        else:
            await it.edit_original_response(content="❌ ไม่พบยอดค้าง", view=None)

class PaymentModal(discord.ui.Modal, title='💳 แจ้งชำระค่าปรับ'):
    evidence_url = discord.ui.TextInput(label='ลิงก์รูปหลักฐาน', placeholder='https://...', required=True)
    note = discord.ui.TextInput(label='หมายเหตุ', style=discord.TextStyle.paragraph, required=False)

    async def on_submit(self, it: discord.Interaction):
        conf = load_json(CONFIG_PATH, {})
        log_ch_id = conf.get('payment_log_ch')
        if not log_ch_id: return await it.response.send_message("❌ ยังไม่ตั้งห้องตรวจสลิป", ephemeral=True)
        
        log_ch = bot.get_channel(int(log_ch_id))
        embed = discord.Embed(title="🧾 แจ้งชำระค่าปรับ", color=0x3498db)
        embed.add_field(name="จาก", value=it.user.mention)
        embed.set_image(url=self.evidence_url.value)
        await log_ch.send(embed=embed, view=AdminVerifyView(it.user.id, 0))
        await it.response.send_message("✅ ส่งหลักฐานแล้ว", ephemeral=True)

class MemberPaymentView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="💳 แจ้งชำระค่าปรับ (ส่งรูป)", style=discord.ButtonStyle.primary, custom_id="btn_pay_fine")
    async def pay_button(self, it, b): await it.response.send_modal(PaymentModal())

class AttendanceMemberSelect(discord.ui.Select):
    def __init__(self, members, label_text):
        opts = [discord.SelectOption(label=m.display_name, value=str(m.id)) for m in members]
        super().__init__(placeholder=label_text, options=opts)
    async def callback(self, it: discord.Interaction):
        await it.response.defer(ephemeral=True)
        view: AttendanceView = self.view
        view.selected_id = int(self.values[0])
        await view.update_message(it)

class AttendanceView(discord.ui.View):
    def __init__(self, members):
        super().__init__(timeout=None)
        self.selected_id = None
        self.results = {}
        g1, g2 = members[:15], members[15:30]
        if g1: self.add_item(AttendanceMemberSelect(g1, "🔍 กลุ่ม 1 (1-15)"))
        if g2: self.add_item(AttendanceMemberSelect(g2, "🔍 กลุ่ม 2 (16-30)"))

    async def update_message(self, it):
        m = it.guild.get_member(self.selected_id)
        embed = discord.Embed(title="📝 เช็กชื่อกิจกรรม", color=0xf1c40f)
        embed.add_field(name="สมาชิก", value=m.mention if m else "ยังไม่ได้เลือก")
        await it.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="แอร์ดรอป 21:00", style=discord.ButtonStyle.secondary)
    async def act1(self, it, b): await self.toggle(it, b, "แอร์ดรอป 21:00")
    @discord.ui.button(label="อีเธอร์", style=discord.ButtonStyle.secondary)
    async def act2(self, it, b): await self.toggle(it, b, "อีเธอร์")
    @discord.ui.button(label="สกายฟอล", style=discord.ButtonStyle.secondary)
    async def act3(self, it, b): await self.toggle(it, b, "สกายฟอล")
    @discord.ui.button(label="แอร์ดรอป 00:00", style=discord.ButtonStyle.secondary)
    async def act4(self, it, b): await self.toggle(it, b, "แอร์ดรอป 00:00")

    async def toggle(self, it, b, name):
        if not self.selected_id: return await it.response.send_message("❌ เลือกคนก่อน", ephemeral=True)
        if self.selected_id not in self.results: self.results[self.selected_id] = set()
        if name in self.results[self.selected_id]:
            self.results[self.selected_id].remove(name)
            b.style = discord.ButtonStyle.secondary
        else:
            self.results[self.selected_id].add(name)
            b.style = discord.ButtonStyle.danger
        await it.response.edit_message(view=self)

    @discord.ui.button(label="💾 บันทึกและส่งยอด", style=discord.ButtonStyle.success, row=4)
    async def save_all(self, it, b):
        conf = load_json(CONFIG_PATH, {})
        ch_id = conf.get('fine_ch')
        if not ch_id: return await it.response.send_message("❌ ยังไม่ตั้งห้องแจ้งยอด", ephemeral=True)
        ch = bot.get_channel(int(ch_id))
        f_data = load_fines()
        msg = "🔔 **สรุปยอดค่าปรับวันนี้**\n"
        for mid, acts in self.results.items():
            cnt = len(acts)
            if cnt == 0: continue
            fine = 500000 if cnt == 4 else cnt * 200000
            f_data["unpaid_fines"][str(mid)] = f_data["unpaid_fines"].get(str(mid), 0) + fine
            msg += f"- <@{mid}> ปรับ **{fine:,} WD**\n"
        save_fines(f_data)
        await ch.send(msg, view=MemberPaymentView())
        await it.response.send_message("✅ สำเร็จ", ephemeral=True)

# --- ย้าย on_ready มาไว้ท้ายสุด และใส่ add_view ให้ครบ ---
@bot.event
async def on_ready():
    # --- 1. ระบบเดิมที่คุณมีอยู่แล้ว ---
    bot.add_view(LeaveMainView())
    bot.add_view(RealtimeRefreshView())
    bot.add_view(MemberPaymentView())
    bot.add_view(AdminVerifyView(0, 0)) # ต้องระวังเรื่องค่า 0, 0 ถ้าโค้ดใหม่เปลี่ยนโครงสร้าง

    # --- 2. เพิ่มระบบใหม่ที่เราเพิ่งสร้าง (สำคัญมาก) ---
    bot.add_view(AdminMainView())      # สำหรับหน้าจัดการหลักที่มีปุ่มปิดเมนู
    bot.add_view(AdminSettingsView())  # สำหรับหน้าตั้งค่าห้อง 8 ห้อง
    bot.add_view(MemberFinesView())     # สำหรับปุ่ม "ตรวจสอบยอด" และ "จ่ายเงิน" ในบิลรวม

    print('✅ Bot DMD Online | System Year: 2026')
    print('🛡️ ระบบ Log ชิดซ้าย และ Auto-Backup พร้อมใช้งาน')

    # --- 3. รันระบบ Task อัตโนมัติ ---
    if not daily_report_task.is_running(): daily_report_task.start()
    if not weekly_report_task.is_running(): weekly_report_task.start()

bot.run(TOKEN)