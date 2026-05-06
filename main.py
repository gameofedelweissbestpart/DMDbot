import discord
from discord.ext import commands, tasks
import json, os, re, asyncio
from datetime import datetime, timedelta

# --- 1. การจัดการข้อมูลแบบแยกไฟล์ (Multi-guild) ---
TOKEN = os.getenv('DISCORD_TOKEN')
DATA_DIR = '/app/data/'
LONG_SEP = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"

# ฟังก์ชันสร้าง Path ไฟล์แยกตาม ID เซิร์ฟเวอร์
def get_path(guild_id, suffix):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    return os.path.join(DATA_DIR, f"{guild_id}_{suffix}.json")

# ฟังก์ชันโหลดข้อมูลแยกตาม Guild
def load_data(guild_id, suffix, default=[]):
    path = get_path(guild_id, suffix)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except: return default
    return default

# ฟังก์ชันบันทึกข้อมูลแยกตาม Guild
def save_data(guild_id, suffix, data):
    path = get_path(guild_id, suffix)
    with open(path, 'w', encoding='utf-8') as f:
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

# --- 2. ระบบตาราง Real-time (แก้ไขให้แยก Guild) ---
async def update_summary_board(guild):
    gid = str(guild.id)
    cfg = load_data(gid, "config", {})
    ch_id = cfg.get("realtime_ch")
    if not ch_id: return
    channel = guild.get_channel(int(ch_id))
    if not channel: return
    
    data = load_data(gid, "leaves", [])
    now = get_thai_time().date()
    
    grouped_leaves = {}
    for e in data:
        try:
            start_dt = datetime.strptime(e['start_date'], "%d/%m/%Y").date()
            end_dt = datetime.strptime(e['end_date'], "%d/%m/%Y").date()
            if start_dt <= now <= end_dt:
                tid = e['target_id']
                if tid not in grouped_leaves: grouped_leaves[tid] = []
                grouped_leaves[tid].append(e)
        except: continue

    desc = f"# 📋 รายชื่อสมาชิกที่แจ้งลา (Real-time)\n{LONG_SEP}\n\n"
    if not grouped_leaves:
        desc += "> 🍃 **ขณะนี้ยังไม่มีสมาชิกแจ้งลาในระบบ**\n\n"
    else:
        for tid, leaves in grouped_leaves.items():
            member = guild.get_member(int(tid))
            display_name = member.display_name if member else (leaves[0].get('name') or "ไม่ทราบชื่อ")
            desc += f" **👤 {display_name}**\n"
            for leaf in leaves:
                dr = leaf['start_date'] if leaf['start_date'] == leaf['end_date'] else f"{leaf['start_date']} - {leaf['end_date']}"
                desc += f" \u17b5 \u17b5 \u17b5 \u17b5 • `[{leaf.get('leave_category','ทั่วไป')}]` วันที่: {dr} `(รวม {leaf.get('total_days', 1)} วัน)`\n"
                
                if leaf['user_id'] != leaf['target_id']: # ดึง Display Name ของผู้แจ้งแทน                
                    executor = guild.get_member(int(leaf['user_id']))
                    ex_name = executor.display_name if executor else f"<@{leaf['user_id']}>"
                    on_behalf = f" **(ผู้แจ้งแทน: {ex_name})**" # คงรูปแบบคำพูดเดิมของคุณเป๊ะๆ
                else:
                    on_behalf = ""
                    
                desc += f" \u17b5 \u17b5 \u17b5 \u17b5 \u17b5 \u17b5 \u17b5 \u17b5 \u17b5 ⤷ **เหตุผล:** {leaf.get('reason', '-')}{on_behalf}\n"
            desc += "\n"
        
    desc += f"{LONG_SEP}\n**📊 สรุปจำนวนคนลาวันนี้: {len(grouped_leaves)} คน**\n"
    desc += f"**📅 อัปเดตล่าสุด: {get_thai_time().strftime('%d/%m/%Y %H:%M น.')}**"
    
    em = discord.Embed(description=desc, color=0x2B2D31)
    target = None
    async for m in channel.history(limit=50):
        if m.author == bot.user and m.embeds and "รายชื่อสมาชิกที่แจ้งลา (Real-time)" in m.embeds[0].description:
            target = m
            break
    
    if target: await target.edit(embed=em, view=RealtimeRefreshView())
    else: await channel.send(embed=em, view=RealtimeRefreshView())

#refresh รีเฟรช
class RealtimeRefreshView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🔄 กดอัปเดตข้อมูลล่าสุด", style=discord.ButtonStyle.success, custom_id="refresh_realtime_board")
    async def refresh_board(self, it: discord.Interaction, b: discord.ui.Button):
        await it.response.send_message("🔄 กำลังอัปเดต...", ephemeral=True)
        await update_summary_board(it.guild)
        await it.edit_original_response(content="✅ อัปเดตข้อมูลล่าสุดเรียบร้อยแล้ว!")
        await asyncio.sleep(3); await it.delete_original_response()

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
        await it.response.defer(ephemeral=True)
        
        # --- ระบุ ID เซิร์ฟเวอร์ปัจจุบัน ---
        gid = str(it.guild.id)
        
        s = self.s_v if self.is_f else self.s_i.value.strip()
        e = self.e_v if self.is_f else self.e_i.value.strip()
        
        if not validate_date(s) or not validate_date(e):
            err_msg = f"**⚠️ รูปแบบวันที่ไม่ถูกต้อง หรือไม่ใช่ปี ค.ศ.!**\n\nท่านกรอกมาว่า: เริ่ม `{s}`, สิ้นสุด `{e}`\n(ตัวอย่าง ค.ศ. ที่ถูกต้อง: 28/04/2026) ❌"
            return await it.followup.send(content=err_msg, view=RetryView(self.title, "", "", self.cat_val, self.t_id, self.is_f, self.re.value), ephemeral=True)
        
        today = get_thai_time().date()
        s_dt = datetime.strptime(s, "%d/%m/%Y").date()
        e_dt = datetime.strptime(e, "%d/%m/%Y").date()

        if s_dt < today:
            return await it.followup.send(content="❌ **ไม่สามารถลาย้อนหลังได้**", view=RetryView(self.title, "", "", self.cat_val, self.t_id, self.is_f, self.re.value), ephemeral=True)
        if e_dt < s_dt:
            return await it.followup.send(content="❌ **วันที่สิ้นสุดต้องไม่มาก่อนวันที่เริ่มต้น!**", view=RetryView(self.title, s, "", self.cat_val, self.t_id, self.is_f, self.re.value), ephemeral=True)

        days = (e_dt - s_dt).days + 1
        if days > 15:
            return await it.followup.send(content=f"❌ **ไม่สามารถแจ้งลาเกิน 15 วันได้ (ท่านลา {days} วัน)**", view=RetryView(self.title, s, e, self.cat_val, self.t_id, self.is_f, self.re.value), ephemeral=True)

        target_uid = self.t_id if self.t_id else str(it.user.id)
        
        # --- แก้ไข Logic: โหลดและบันทึกแยกไฟล์ตาม Guild ID ---
        d = load_data(gid, "leaves", [])
        d.append({
            "user_id": str(it.user.id),
            "target_id": target_uid,
            "name": it.user.display_name,
            "leave_category": self.cat_val,
            "start_date": s,
            "end_date": e,
            "total_days": days,
            "reason": self.re.value
        })
        save_data(gid, "leaves", d)
        
        # --- อัปเดตบอร์ดเฉพาะเซิร์ฟเวอร์ที่ทำรายการ ---
        await update_summary_board(it.guild) 
        
        # --- แก้ไข Logic: โหลด Config แยกไฟล์ตาม Guild ID ---
        cfg = load_data(gid, "config", {})
        log_ch_id = cfg.get("log_ch")
        
        if log_ch_id:
            log_ch = bot.get_channel(int(log_ch_id))
            if log_ch:
                target_m = it.guild.get_member(int(target_uid))
                target_name = target_m.display_name if target_m else f"ID: {target_uid}"
                executor_name = it.user.display_name

                is_on_behalf = True if self.t_id and self.t_id != str(it.user.id) else False
                log_title = "📌 บันทึกการแจ้งลาแทนเพื่อน" if is_on_behalf else "📌 บันทึกการแจ้งลาใหม่"
                log_color = 0x3498db if is_on_behalf else 0x2ecc71
                
                log_em = discord.Embed(title=log_title, color=log_color)
                on_behalf_txt = f"\n**👮 ผู้แจ้งลาแทน:** {executor_name}" if is_on_behalf else ""
                dr = s if s == e else f"{s} - {e}"
                
                log_em.description = (
                    f"**👤 สมาชิกที่ลา:** {target_name}{on_behalf_txt}\n\n"
                    f"**📝 ประเภท:** {self.cat_val}\n"
                    f"**📅 วันที่ลา:** {dr} `(รวม {days} วัน)`\n"
                    f"**💬 เหตุผล:** {self.re.value}\n\n"
                    f"{LONG_SEP}"
                )
                log_em.set_footer(text=f"บันทึกเมื่อ: {get_thai_time().strftime('%d/%m/%Y %H:%M')} น.")
                await log_ch.send(embed=log_em)
        
        success_msg = await it.followup.send(content='✅ ระบบบันทึกใบลาของคุณเรียบร้อยแล้ว!', ephemeral=True)
        await asyncio.sleep(3)
        try: await success_msg.delete()
        except: pass

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
        super().__init__(timeout=None) 

    @discord.ui.button(label="⚠️ ยืนยันล้างข้อมูลเก่า (ย้อนหลัง 1 เดือน)", 
                       style=discord.ButtonStyle.success, 
                       custom_id="admin_confirm_cleanup_v1") 
    async def confirm(self, it: discord.Interaction, b: discord.ui.Button):
        # [1] จองคิวการตอบกลับแบบข้อความลับ (Ephemeral)
        await it.response.defer(ephemeral=True)
        
        # --- เริ่มการแก้ไข Logic แยกไฟล์ตาม Guild ---
        gid = str(it.guild.id)
        path_leaves = get_path(gid, "leaves")
        path_config = get_path(gid, "config")
        
        # [2] สำรองข้อมูลส่งให้เฉพาะ "ผู้ที่กดปุ่ม" เท่านั้น (แยกตาม Guild)
        try:
            f_send = []
            if os.path.exists(path_leaves): f_send.append(discord.File(path_leaves))
            if os.path.exists(path_config): f_send.append(discord.File(path_config))
            
            # ส่ง DM ตรงหา it.user (ผู้กดปุ่ม) พร้อมคำพูดเดิม
            await it.user.send(
                f"📦 **Backup ก่อน Cleanup:** ท่านได้ดำเนินการล้างข้อมูลเก่า\nนี่คือไฟล์สำรองข้อมูลส่วนตัวของท่านครับ:", 
                files=f_send
            )
        except discord.Forbidden:
            # คงคำพูดเดิม
            return await it.followup.send("❌ ไม่สามารถส่งไฟล์สำรองได้ โปรดเปิด DM แล้วลองใหม่อีกครั้ง", ephemeral=True)

        # [3] กรองข้อมูลย้อนหลัง 30 วัน (แยกตาม Guild)
        d = load_data(gid, "leaves", [])
        now = get_thai_time().date()
        threshold_date = now - timedelta(days=30) 
        filtered_data = []
        removed_count = 0
        
        for entry in d:
            try:
                end_dt = datetime.strptime(entry['end_date'], "%d/%m/%Y").date()
                if end_dt >= threshold_date:
                    filtered_data.append(entry)
                else:
                    removed_count += 1
            except:
                removed_count += 1

        # [4] บันทึกข้อมูลและแจ้งผล (แยกตาม Guild)
        save_data(gid, "leaves", filtered_data)
        await update_summary_board(it.guild) # ส่ง Object Guild เพื่ออัปเดตบอร์ดให้ถูกที่
        
        # ส่ง Log สีส้มเข้าห้อง Log ตามปกติ
        cfg = load_data(gid, "config", {})
        log_ch_id = cfg.get("log_ch")
        if log_ch_id:
            log_ch = bot.get_channel(int(log_ch_id))
            if log_ch:
                l_em = discord.Embed(title="⚠️ ประกาศ: Cleanup ข้อมูลใบลาประจำเดือน", color=0xf39c12)
                l_em.description = (
                    f"**👮 ผู้ดำเนินการ:** {it.user.display_name}\n"
                    f"**🧹 ลบข้อมูลที่เก่ากว่า:** {threshold_date.strftime('%d/%m/%Y')}\n"
                    f"**📊 จำนวนที่ลบออก:** `{removed_count}` รายการ\n"
                    f"**📦 ข้อมูลคงเหลือ:** `{len(filtered_data)}` รายการ\n\n"
                    f"{LONG_SEP}"
                )
                l_em.set_footer(text=f"บันทึกเมื่อ: {get_thai_time().strftime('%d/%m/%Y %H:%M:%S')}")
                await log_ch.send(embed=l_em)
            
        # [5] อัปเดตข้อความลับแจ้งผู้ใช้ (คงคำพูดเดิม)[cite: 1]
        await it.edit_original_response(
            content=f"✅ Cleanup สำเร็จ! ลบข้อมูลเก่า `{removed_count}` รายการเรียบร้อยแล้ว (ไฟล์ส่งเข้า DM ท่านแล้ว)", 
            view=None
        )
        
        await asyncio.sleep(3)
        try:
            await it.delete_original_response()
        except:
            pass

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.danger, custom_id="admin_close_cleanup_panel")
    async def close_menu(self, it: discord.Interaction, button: discord.ui.Button):
        try:
            await it.response.defer()
            await it.delete_original_response()
        except:
            pass

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.danger, custom_id="admin_close_cleanup_panel")
    async def close_menu(self, it: discord.Interaction, button: discord.ui.Button):
        try:
            await it.response.defer()
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
        super().__init__(timeout=None) # บังคับให้ปุ่มไม่หมดอายุ
        self.cat = cat
        self.temp_ch = None
        self.add_item(AdminSubChannelSelect())

    @discord.ui.button(label="ยืนยันตั้งค่า", 
                       style=discord.ButtonStyle.success, 
                       custom_id="admin_save_room_config") # เพิ่ม ID ตรงนี้
    async def confirm(self, it: discord.Interaction, b):
        # --- คงคำพูดเดิมของคุณไว้ทั้งหมด ---
        if not self.temp_ch:
            return await it.response.send_message("❌ กรุณาเลือกห้องก่อน!", ephemeral=True)
        
        await it.response.defer(ephemeral=True)
        
        # --- เริ่มการแก้ไข Logic แยกไฟล์ตาม Guild ---
        gid = str(it.guild.id) 
        
        # โหลด Config เฉพาะของ Guild นี้
        cfg = load_data(gid, "config", {}) 
        cfg[self.cat] = str(self.temp_ch)
        
        # บันทึก Config ลงไฟล์แยกของ Guild นี้
        save_data(gid, "config", cfg) 
        
        if self.cat == "leave_ch":
            # ปรับหัวข้อ: ใหญ่พิเศษขีดเส้นใต้ + หมายเหตุใหม่ตามสั่ง (คงเดิม 100%)[cite: 1]
            em = discord.Embed(
                title=None, 
                description=(
                    "# __📋 ระบบการแจ้งลาแก๊ง Dark Monday__\n"
                    "กรุณากดปุ่มด้านล่างเพื่อทำรายการที่ท่านต้องการได้เลยครับ\n\n"
                    "**⚠️ __หมายเหตุสำคัญ__ ⚠️**\n"
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
            # ส่ง Object Guild เข้าไปเพื่อให้อัปเดตบอร์ดได้ถูกเซิร์ฟเวอร์
            await update_summary_board(it.guild)
        
        # คงคำพูดเดิม[cite: 1]
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

# --- Class สำหรับเป็นหน้ากาก (Container) ให้ Dropdown เลือกหัวข้อ ---
class SubMenuView(discord.ui.View):
    def __init__(self, it, select_item):
        super().__init__(timeout=120)
        self.add_item(select_item)

# --- ส่วนที่ 1: หน้าเลือกเลือกระบบ (ลา หรือ ปรับเงิน) ---
class CategorySelectionView(discord.ui.View):
    def __init__(self):
        # 1. ตั้งค่า timeout เป็น None เพื่อให้ View นี้ไม่หมดอายุ
        super().__init__(timeout=None)

    # 2. ตรวจสอบว่าปุ่มมี custom_id ที่แน่นอน
    @discord.ui.button(label="📝 ระบบแจ้งลา", style=discord.ButtonStyle.primary, custom_id="setup_leave_system")
    async def leave_system_setup(self, it: discord.Interaction, button: discord.ui.Button):
        opts = [
            discord.SelectOption(label="📝 ห้องปุ่มแจ้งลา", value="leave_ch"),
            discord.SelectOption(label="📋 ตาราง Real-time", value="realtime_ch"),
            discord.SelectOption(label="📌 Log แจ้งลา", value="log_ch"),
            discord.SelectOption(label="📊 ประวัติรายวัน", value="daily_ch"),
            discord.SelectOption(label="📊 สรุปประวัติรายสัปดาห์", value="weekly_ch"),
        ]
        # เมื่อเปลี่ยนหน้าเมนู แนะนำให้ใช้ View ใหม่ที่รองรับ Persistent เช่นกัน
        await it.response.edit_message(content="🛠 **ระบบแจ้งลา:** เลือกหัวข้อที่ต้องการตั้งค่า:", view=SubMenuView(it, AdminCatSelect(opts)))

    @discord.ui.button(label="💰 ระบบแจ้งปรับเงิน", style=discord.ButtonStyle.primary, custom_id="setup_fine_system")
    async def fine_system_setup(self, it: discord.Interaction, button: discord.ui.Button):
        opts = [
            discord.SelectOption(label="📋 แจ้งค่าปรับ Real-time", value="fine_realtime_ch"),
            discord.SelectOption(label="📌 Log การปรับเงิน", value="fine_log_ch"),
            discord.SelectOption(label="✅ อนุมัติการชำระเงิน", value="fine_approve_ch"),
        ]
        await it.response.edit_message(content="🛠 **ระบบแจ้งปรับเงิน:** เลือกหัวข้อที่ต้องการตั้งค่า:", view=SubMenuView(it, AdminCatSelect(opts)))

    @discord.ui.button(label="ปิดเมนู", style=discord.ButtonStyle.danger, custom_id="admin_close_setup_category")
    async def close_menu(self, it: discord.Interaction, button: discord.ui.Button):
        try:
            await it.response.defer()
            await it.delete_original_response()
        except:
            pass    

class AdminPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📍 ตั้งค่าห้องต่างๆ", style=discord.ButtonStyle.primary, custom_id="admin_room_settings")
    async def set_l(self, it, b):
        # เรียกหน้าเลือกหมวดหมู่
        await it.response.send_message("📂 **เลือกหมวดหมู่ที่ต้องการจัดการ:**", view=CategorySelectionView(), ephemeral=True)

    @discord.ui.button(label="📋 ระบบลา", style=discord.ButtonStyle.primary, custom_id="admin_leave_system_main")
    async def leave_system(self, it: discord.Interaction, b):
        # แก้ไขจุดที่มีวงเล็บเปิดค้างไว้ โดยเติมวงเล็บปิดให้สมบูรณ์ที่ท้ายคำสั่ง
        await it.response.send_message(
            content="📑 **เมนูจัดการระบบลา:** เลือกการดำเนินการที่ต้องการ", 
            view=AdminLeaveManagementView(), 
            ephemeral=True
        ) # <--- ตรวจสอบวงเล็บปิดตรงนี้ ต้องมีวงเล็บปิดครอบพารามิเตอร์ทั้งหมด    

# --- 4. ส่วน Admin (คงคำพูดเดิม / แก้ Logic แยกไฟล์) ---
class AdminLeaveManagementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="⚙️ จัดการใบลาทั้งหมด", style=discord.ButtonStyle.primary, custom_id="admin_manage_all_leaves_v2")
    async def manage_all(self, it: discord.Interaction, b):
        gid = str(it.guild.id)
        d = load_data(gid, "leaves", []) # โหลดข้อมูลแยกตาม Guild
        now_date = get_thai_time().date()
        # [1] กำหนดเกณฑ์ย้อนหลัง 14 วัน
        limit_back_date = now_date - timedelta(days=14)
        all_opts = [] # เปลี่ยนเป็นเก็บทั้งหมดก่อน
        
        for i, e in enumerate(d):
            try:
                target_end_date = datetime.strptime(e['end_date'], "%d/%m/%Y").date()
                if target_end_date < limit_back_date: 
                    continue
            except: continue
            
            target_m = it.guild.get_member(int(e['target_id']))
            tn = target_m.display_name if target_m else e['name']
            dr = e['start_date'] if e['start_date'] == e['end_date'] else f"{e['start_date']} - {e['end_date']}"
            
            all_opts.append(discord.SelectOption(
                label=f"{tn} | {dr}",
                description=f"โดย: {it.guild.get_member(int(e['user_id'])).display_name if it.guild.get_member(int(e['user_id'])) else 'ระบบ'}",
                value=str(i)
            ))
            
        if not all_opts: 
            return await it.response.send_message("🍃 **ขณะนี้ไม่มีรายการใบลาที่กำลังดำเนินการอยู่**", ephemeral=True)

        # --- ส่วนแบ่ง Dropdown ชุดละ 25 รายการ ---
        view = SubMenuView(it) # สร้าง View เปล่า
        # แบ่ง list all_opts ออกเป็นส่วนๆ ชุดละ 25
        for start in range(0, len(all_opts), 25):
            end = start + 25
            chunk = all_opts[start:end]
            # ใส่เลขหน้ากำกับที่ Placeholder เพื่อให้แอดมินไม่งง (รักษาคำเดิมและเพิ่มข้อมูลหน้า)
            placeholder_text = f"🔍 เลือกใบลา (รายการที่ {start+1}-{min(end, len(all_opts))})..."
            view.add_item(AdminActionSelect(chunk, placeholder_text))    
            
        await it.response.edit_message(
            content="🛠 **แอดมินจัดการใบลา:** เลือกรายการที่ต้องการจัดการ:", 
            view=view
        )

    @discord.ui.button(label="🗑️ ล้างข้อมูลใบลา (30 วัน)", style=discord.ButtonStyle.primary, custom_id="admin_cleanup_trigger_v2")
    async def cleanup(self, it: discord.Interaction, b):
        txt = "⚠️ **คุณยืนยันที่จะ Cleanup ข้อมูลใบลาที่เก่ากว่า 1 เดือนใช่หรือไม่?**\nระบบจะส่งไฟล์ Backup ให้คุณก่อนดำเนินการ"
        await it.response.send_message(content=txt, view=ConfirmClearView(), ephemeral=True)

    @discord.ui.button(label="ปิดเมนู", style=discord.ButtonStyle.danger, custom_id="admin_close_leave_system_v2")
    async def close_menu(self, it: discord.Interaction, b):
        try:
            await it.response.defer()
            await it.delete_original_response()
        except: pass

class AdminActionSelect(discord.ui.Select):
    # ปรับปรุงให้รับ placeholder_str เพื่อรองรับการแบ่งหน้า
    def __init__(self, opts, placeholder_str="🔍 เลือกใบลาที่ต้องการจัดการ..."):
        super().__init__(placeholder=placeholder_str, options=opts)
    
    async def callback(self, it: discord.Interaction):
        # --- เริ่มการแก้ไข Logic แยกไฟล์ตาม Guild ---
        gid = str(it.guild.id)
        
        idx = int(self.values[0])
        # โหลดข้อมูลใบลาเฉพาะของ Guild นี้
        d = load_data(gid, "leaves", []) 
        
        if 0 <= idx < len(d):
            od = d[idx]
            # คงคำพูดและรูปแบบเดิมของคุณไว้ทั้งหมด
            em = discord.Embed(title="⚙️ เมนูจัดการสำหรับผู้ดูแล", color=0xe67e22)
            em.description = (f"**👤 สมาชิก:** <@{od['target_id']}>\n"
                              f"**📅 วันที่:** {od['start_date']} - {od['end_date']}\n"
                              f"**📝 ประเภท:** {od.get('leave_category','ทั่วไป')}\n"
                              f"**💬 เหตุผล:** {od['reason']}")
            
            # ส่งเมนูทางเลือกถัดไป (แก้ไข/ยกเลิก)
            await it.response.edit_message(content="❓ **ท่านต้องการดำเนินการอย่างไรกับใบลานี้?**", 
                                           embed=em, view=AdminFinalActionView(idx, od))

class AdminFinalActionView(discord.ui.View):
    def __init__(self, idx, od):
        super().__init__(timeout=None)
        self.idx, self.od = idx, od

    @discord.ui.button(label="📝 แก้ไขข้อมูลใบลา", style=discord.ButtonStyle.secondary, custom_id="admin_edit_master_btn")
    async def edit_details(self, it: discord.Interaction, b: discord.ui.Button):
        # คงรายการประเภทการลาเดิมของคุณไว้ทั้งหมด
        categories = ["ลาพีคไทม์", "ลาแอร์ดรอป 21:00 น.", "ลาแอร์ดรอป 00:00 น.", "ลาอีเธอร์ยักษ์", "ลาสกายฟอล", "ลาซ้อม", "ลาอื่นๆ (ระบุในเหตุผล)"]
        opts = [discord.SelectOption(label=f"คงประเภทเดิม: {self.od.get('leave_category', 'ทั่วไป')}", value="KEEP_OLD", emoji="📌")]
        for cat in categories:
            opts.append(discord.SelectOption(label=cat, value=cat, emoji="📝"))
            
        # คงคำพูดเดิมของคุณไว้ 100%
        await it.response.edit_message(
            content="🎯 **ขั้นตอนที่ 1:** เลือกประเภทการลาที่ต้องการ (หรือใช้ค่าเดิม)", 
            embed=None, 
            view=AdminEditCategoryView(self.idx, self.od, opts)
        )

    @discord.ui.button(label="🛑 ยกเลิกใบลานี้", style=discord.ButtonStyle.danger, custom_id="admin_cancel_leave_btn")
    async def cancel(self, it: discord.Interaction, b: discord.ui.Button):
        # ส่งค่า True เพื่อบอกว่าเป็นรายการจากแอดมิน และส่งต่อข้อมูลไปยัง Modal
        await it.response.send_modal(CancelReasonModal(self.idx, self.od, is_admin_request=True))

    @discord.ui.button(label="🔙 ย้อนกลับ", style=discord.ButtonStyle.secondary, custom_id="admin_back_to_select_leave_btn", row=1)
    async def back(self, it: discord.Interaction, b: discord.ui.Button):
        # ย้อนกลับไปหน้าจัดการหลัก ซึ่งใน AdminLeaveManagementView เราได้แก้ Logic แยกไฟล์ไว้แล้ว[cite: 1]
        await it.response.edit_message(
            content="🛠 **แอดมินจัดการใบลา:** เลือกรายการที่ต้องการจัดการอีกครั้ง:", 
            embed=None, 
            view=AdminLeaveManagementView()
        )

class AdminEditCategoryView(discord.ui.View):
    def __init__(self, idx, od, opts):
        super().__init__(timeout=120)
        self.idx, self.od = idx, od
        self.add_item(AdminEditCategorySelect(idx, od, opts))

    @discord.ui.button(label="🔙 ย้อนกลับ", style=discord.ButtonStyle.secondary, row=1, custom_id="admin_edit_back_to_final")
    async def back(self, it: discord.Interaction, b: discord.ui.Button):
        # คงคำพูดและรูปแบบ Embed เดิมของคุณไว้ 100%
        em = discord.Embed(title="⚙️ เมนูจัดการสำหรับผู้ดูแล", color=0xe67e22)
        em.description = (f"**👤 สมาชิก:** <@{self.od['target_id']}>\n"
                          f"**📅 วันที่:** {self.od['start_date']} - {self.od['end_date']}\n"
                          f"**📝 ประเภท:** {self.od.get('leave_category','ทั่วไป')}\n"
                          f"**💬 เหตุผล:** {self.od['reason']}")
        await it.response.edit_message(content="❓ **ท่านต้องการดำเนินการอย่างไรกับใบลานี้?**", embed=em, view=AdminFinalActionView(self.idx, self.od))

class AdminEditCategorySelect(discord.ui.Select):
    def __init__(self, idx, od, opts):
        # คง placeholder เดิม
        super().__init__(placeholder="🔍 เลือกประเภทการลาใหม่...", options=opts, custom_id="admin_category_select_dropdown")
        self.idx, self.od = idx, od
    
    async def callback(self, it: discord.Interaction):
        # คง Logic การเลือกประเภท (เดิมหรือใหม่) ตามที่คุณเขียนไว้
        final_cat = self.od.get('leave_category', 'ทั่วไป') if self.values[0] == "KEEP_OLD" else self.values[0]
        
        # ส่งต่อไปยัง Modal แก้ไขรายละเอียด (ซึ่งเราได้แก้ Logic แยกไฟล์ไว้แล้วในขั้นตอนก่อนหน้า)[cite: 1]
        await it.response.send_modal(AdminEditDetailsModal(self.idx, self.od, final_cat))

# --- แก้ไข Logic ใน AdminEditDetailsModal (คำเดิม 100% + เพิ่มเงื่อนไข (คงเดิม)) ---
class AdminEditDetailsModal(discord.ui.Modal):
    def __init__(self, idx, od, selected_cat):
        super().__init__(title="แก้ไขใบลาแบบละเอียด (Admin)")
        self.idx, self.od, self.selected_cat = idx, od, selected_cat
        
        self.s_i = discord.ui.TextInput(label="วันเริ่มลา (วว/ดด/ปปปป) *ค.ศ.*", default=od['start_date'], required=True)
        self.e_i = discord.ui.TextInput(label="วันสิ้นสุด (วว/ดด/ปปปป) *ค.ศ.*", default=od['end_date'], required=True)
        self.re = discord.ui.TextInput(label="เหตุผลการลา", style=discord.TextStyle.paragraph, default=od['reason'], required=True)
        self.admin_re = discord.ui.TextInput(label="หมายเหตุจากแอดมิน (ทำไมถึงแก้?)", placeholder="ระบุเหตุผลเพื่อบันทึกใน Log...", required=True)
        
        self.add_item(self.s_i)
        self.add_item(self.e_i)
        self.add_item(self.re)
        self.add_item(self.admin_re)

    async def on_submit(self, it: discord.Interaction):
        await it.response.defer(ephemeral=True)
        gid = str(it.guild.id)
        
        new_s = self.s_i.value.strip()
        new_e = self.e_i.value.strip()
        new_reason = self.re.value.strip()
        admin_note = self.admin_re.value.strip()
        
        if not validate_date(new_s) or not validate_date(new_e):
            return await it.followup.send("❌ รูปแบบวันที่ไม่ถูกต้อง! (วว/ดด/ปปปป)", ephemeral=True)

        d = load_data(gid, "leaves", []) 
        if 0 <= self.idx < len(d):
            entry = d[self.idx]
            old_s, old_e = entry['start_date'], entry['end_date']
            old_cat = entry.get('leave_category', 'ทั่วไป')
            old_days = entry.get('total_days', 1)
            old_reason = entry.get('reason', '-')
            
            try:
                s_dt = datetime.strptime(new_s, "%d/%m/%Y").date()
                e_dt = datetime.strptime(new_e, "%d/%m/%Y").date()
                if e_dt < s_dt:
                    return await it.followup.send("❌ วันสิ้นสุดต้องไม่มาก่อนวันเริ่ม!", ephemeral=True)
                new_days = (e_dt - s_dt).days + 1
            except:
                return await it.followup.send("❌ เกิดข้อผิดพลาดในการคำนวณวันที่!", ephemeral=True)

            # --- [เริ่มต้น Logic เปรียบเทียบตามเงื่อนไขใหม่] ---
            # 1. วันที่ลา
            if old_s == new_s and old_e == new_e:
                date_txt = f"`{old_s}-{old_e}` (คงเดิม)"
            else:
                date_txt = f"`{old_s}-{old_e}` ➔ **`{new_s}-{new_e}`**"

            # 2. ประเภทการลา
            cat_txt = f"`{old_cat}` (คงเดิม)" if old_cat == self.selected_cat else f"`{old_cat}` ➔ **`{self.selected_cat}`**"
            
            # 3. จำนวนวัน
            days_txt = f"`{old_days}` วัน (คงเดิม)" if old_days == new_days else f"`{old_days}` ➔ **`{new_days}` วัน**"
            
            # 4. เหตุผล
            reason_txt = f"`{old_reason}` (คงเดิม)" if old_reason == new_reason else f"`{old_reason}` ➔ **`{new_reason}`**"
            # --- [จบ Logic เปรียบเทียบ] ---

            entry.update({
                "start_date": new_s, 
                "end_date": new_e,
                "total_days": new_days,
                "leave_category": self.selected_cat,
                "reason": new_reason
            })
            
            save_data(gid, "leaves", d) 
            await update_summary_board(it.guild)
            
            cfg = load_data(gid, "config", {}) 
            log_ch_id = cfg.get("log_ch")
            if log_ch_id:
                log_ch = bot.get_channel(int(log_ch_id))
                if log_ch:
                    target_m = it.guild.get_member(int(self.od['target_id']))
                    tn = target_m.display_name if target_m else self.od['name']
                    
                    em = discord.Embed(title="📌 บันทึกการจัดการโดยผู้ดูแล (แก้ไขใบลา)", color=0xe67e22)
                    # ใช้คำพูดเดิม 100% แทรกตัวแปรที่มี Logic ใหม่เข้าไป
                    em.description = (
                        f"**👤 สมาชิกที่ลา:** {tn}\n"
                        f"**👮 ผู้ดำเนินการ:** {it.user.display_name} (Admin)\n\n"
                        f"**🔄 รายละเอียดการเปลี่ยนแปลง:**\n"
                        f"• **วันที่ลา:** {date_txt}\n"
                        f"• **ประเภทการลา:** {cat_txt}\n"
                        f"• **จำนวนวัน:** {days_txt}\n"
                        f"• **เหตุผล:** {reason_txt}\n\n"
                        f"**🛑 หมายเหตุจากแอดมิน:** {admin_note}\n\n"
                        f"{LONG_SEP}"
                    )
                    em.set_footer(text=f"บันทึกเมื่อ: {get_thai_time().strftime('%d/%m/%Y %H:%M:%S')}")
                    await log_ch.send(embed=em)

            await it.edit_original_response(content="✅ อัปเดตข้อมูลใบลาเรียบร้อยแล้ว!", view=None)        
            await asyncio.sleep(3) 
            try: await it.delete_original_response() 
            except: pass        

# --- 5. งานรายวัน (ฉบับแก้ไข Syntax + นับจำนวนคนแบบ Unique) ---
# --- ฟังก์ชันสรุปรายวัน (คงคำพูดเดิม 100% / แก้ Logic แยกไฟล์ตาม Guild) ---
@tasks.loop(minutes=1)
async def daily_report_task():
    n = get_thai_time()
    
    # ส่งรายงานเวลา 00:05 น. ของทุกวัน
    if n.hour == 0 and n.minute == 5:
        # แก้ Logic: วนลูปทุก Guild ที่บอทอยู่เพื่อให้แยกไฟล์กันเด็ดขาด
        for guild in bot.guilds:
            gid = str(guild.id)
            # แก้ Logic: โหลด Config แยกตาม Guild ID
            cfg = load_data(gid, "config", {})
            ch_id = cfg.get("daily_ch", 0)
            
            if ch_id:
                ch = bot.get_channel(int(ch_id))
                if ch:
                    # แก้ Logic: โหลดใบลาแยกตาม Guild ID
                    data = load_data(gid, "leaves", [])
                    target_date = (n - timedelta(days=1)).date()
                    
                    # ประมวลผลคนลาในวันนั้น (คง Logic เดิมของคุณ)
                    daily_grouped = {}
                    cat_counts = {} # เพิ่มตัวแปรเก็บสถิติประเภทการลา

                    for e in data:
                        try:
                            start_dt = datetime.strptime(e['start_date'], "%d/%m/%Y").date()
                            end_dt = datetime.strptime(e['end_date'], "%d/%m/%Y").date()
                            if start_dt <= target_date <= end_dt:
                                tid = e['target_id']
                                if tid not in daily_grouped:
                                    daily_grouped[tid] = []
                                daily_grouped[tid].append(e)
                                
                                # เก็บสถิติประเภทการลา
                                cat = e.get('leave_category', 'ทั่วไป')
                                cat_counts[cat] = cat_counts.get(cat, 0) + 1
                        except:
                            continue

                    # --- ส่วนสร้าง Embed (คงคำพูดและสัญลักษณ์เดิมของคุณทั้งหมด) ---
                    separator = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
                    em = discord.Embed(
                        title="📋 __รายงานสรุปการลาประจำวัน__",
                        description=f"📅 **ของวันที่ {target_date.strftime('%d/%m/%Y')}**\n{separator}",
                        color=0x2B2D31
                    )

                    if not daily_grouped:
                        em.description += "\n\n 🍃 **เมื่อวานนี้ไม่มีสมาชิกแจ้งลาในระบบ**"
                    else:
                        msg = ""
                        for tid, leaves in daily_grouped.items():
                            member = guild.get_member(int(tid))
                            target_name = member.display_name if member else tid
                            msg += f"👤 **{target_name}**\n"
                            for leaf in leaves:
                                msg += f" ┗ ` {leaf.get('leave_category','ทั่วไป')} `\n"
                                msg += f" \u17b5 \u17b5 \u17b5 └ **เหตุผล:** {leaf['reason']}\n"
                            msg += "\n"
                        
                        em.add_field(name="\u200b", value=msg, inline=False)
                    
                    # --- ส่วนสรุปยอดรวมที่นำกลับมาให้ครบตามที่คุณแจ้ง ---
                    summary_msg = f"{separator}\n"
                    summary_msg += f"📊 **สรุปจำนวนคนลา: {len(daily_grouped)} คน**\n" # ใช้ len(daily_grouped) เพื่อความ Unique ตามเดิม
                    for cat_name, count in cat_counts.items(): # เติม : ตามเดิม
                        summary_msg += f"• {cat_name}: `{count}` ครั้ง\n"
                    
                    em.add_field(name="\u200b", value=summary_msg, inline=False)

                    # คงส่วนท้ายของ Embed ให้เหมือนเดิมเป๊ะ
                    em.set_footer(text=f"ระบบรายงานอัตโนมัติ: {get_thai_time().strftime('%d/%m/%Y %H:%M น.')}")
                    await ch.send(embed=em)

    # --- ฟังก์ชันสรุปรายสัปดาห์ (วางต่อจาก daily_report_task หรือก่อน bot.run) ---
# --- ฟังก์ชันสรุปรายสัปดาห์ (คงคำพูดเดิม / แก้ Logic แยกไฟล์ตาม Guild) ---
@tasks.loop(minutes=1)
async def weekly_report_task():
    n = get_thai_time()
    
    # ส่งรายงานทุกวันจันทร์ เวลา 00:10 น.
    if n.weekday() == 0 and n.hour == 0 and n.minute == 10:
        # แก้ Logic: วนลูปทุก Guild ที่บอทอยู่เพื่อให้แยกไฟล์กันเด็ดขาด
        for guild in bot.guilds:
            gid = str(guild.id)
            # แก้ Logic: โหลด Config แยกตาม Guild ID
            cfg = load_data(gid, "config", {})
            ch_id = cfg.get("weekly_ch", 0)
            
            if ch_id:
                ch = bot.get_channel(int(ch_id))
                if ch:
                    # แก้ Logic: โหลดใบลาแยกตาม Guild ID
                    all_data = load_data(gid, "leaves", [])
                    start_week = (n - timedelta(days=7)).date()
                    end_week = (n - timedelta(days=1)).date()
                    
                    # กรองสมาชิกตาม Role (คง ID เดิมของคุณ)[cite: 1]
                    target_role_id = 1456228588968739028
                    exclude_role_id = 1498319593939144755
                    gang_members = [m for m in guild.members if any(r.id == target_role_id for r in m.roles) and not any(r.id == exclude_role_id for r in m.roles)]

                    # --- ส่วนประมวลผลข้อมูล (Logic ใหม่แบบแยก Guild) ---
                    leave_stats = {} 
                    cat_counts = {}

                    for entry in all_data:
                        try:
                            s_d = datetime.strptime(entry['start_date'], "%d/%m/%Y").date()
                            e_d = datetime.strptime(entry['end_date'], "%d/%m/%Y").date()
                            if not (e_d < start_week or s_d > end_week):
                                uid = entry['target_id']
                                overlap_s = max(s_d, start_week)
                                overlap_e = min(e_d, end_week)
                                days = (overlap_e - overlap_s).days + 1
                                
                                if uid not in leave_stats:
                                    leave_stats[uid] = {'days': 0, 'cats': {}}
                                
                                leave_stats[uid]['days'] += days
                                cat = entry.get('leave_category', 'ทั่วไป')
                                leave_stats[uid]['cats'][cat] = leave_stats[uid]['cats'].get(cat, 0) + 1
                                cat_counts[cat] = cat_counts.get(cat, 0) + 1
                        except: continue

                    # --- ส่วนสร้างรายการรายชื่อสมาชิก (คงคำพูดและสัญลักษณ์เดิม) ---[cite: 1]
                    away_list = []
                    active_list = []
                    for m in gang_members:
                        uid_str = str(m.id)
                        if uid_str in leave_stats:
                            st = leave_stats[uid_str]
                            cats_txt = ", ".join([f"{c} ({v} ครั้ง)" for c, v in st['cats'].items()])
                            info = (
                                f"👤 **{m.display_name}** — `{st['days']}` วัน\n"
                                f" \u17b5 \u17b5 \u17b5 ⤷ **ประเภท:** {cats_txt}" # คงลูกศร ⤷ และ \u17b5[cite: 1]
                            )
                            away_list.append(info)
                        else:
                            active_list.append(f"👤 **{m.display_name}**")

                    # --- ส่วนสร้าง Embed (คงคำพูดและสัญลักษณ์เดิม) ---[cite: 1]
                    separator = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
                    em = discord.Embed(
                        title="📋 __รายงานสรุปการลาประจำสัปดาห์__",
                        description=f"📅 **ช่วงวันที่ {start_week.strftime('%d/%m/%Y')} - {end_week.strftime('%d/%m/%Y')}**\n{separator}",
                        color=0x2B2D31
                    )

                    away_text = "\n".join(away_list) if away_list else "ไม่มีสมาชิกแจ้งลา"
                    # คงสัญลักษณ์ ❎[cite: 1]
                    em.add_field(name="❎ สมาชิกที่แจ้งลา (สัปดาห์นี้)", value=f"{away_text}\n*(รวม: {len(away_list)} คน)*", inline=False)

                    active_text = "\n".join(active_list) if active_list else "ไม่มีสมาชิก Active"
                    em.add_field(name="✅ สมาชิกที่ไม่ได้ลาเลย (Active)", value=f"{active_text}\n*(รวม: {len(active_list)} คน)*", inline=False)

                    # สรุปยอดรวมท้ายประกาศ[cite: 1]
                    total_m = len(gang_members)
                    active_percent = (len(active_list) / total_m * 100) if total_m > 0 else 0
                    summary_msg = f"{separator}\n📊 **สรุปยอดรวมทั้งหมด: {total_m} คน**\n"
                    for c_name, c_num in cat_counts.items():
                        summary_msg += f"• {c_name}: `{c_num}` ครั้ง\n"
                    
                    if cat_counts:
                        summary_msg += f"\n📈 **สถิติ:** สัปดาห์นี้สมาชิกลา **\"{max(cat_counts, key=cat_counts.get)}\"** มากที่สุด"
                    summary_msg += f"\n✨ **ความแอคทีฟสัปดาห์นี้: {active_percent:.1f}%**"
                    
                    em.add_field(name="\u200b", value=summary_msg, inline=False)
                    em.set_footer(text=f"ระบบรายงานอัตโนมัติ • {n.strftime('%d/%m/%Y %H:%M น.')}")

                    await ch.send(embed=em)

# --- อย่าลืมเพิ่มการสั่งรัน Task ใน on_ready ---
# ในฟังก์ชัน on_ready() ของคุณ ให้เพิ่มบรรทัดนี้:
# if not weekly_report_task.is_running():
#     weekly_report_task.start()

# --- 6. ระบบยกเลิกใบลา (ฉบับปรับปรุง: ตัดชื่อผู้ดำเนินการตามเงื่อนไขที่คุณย้ำ) ---
class CancelReasonModal(discord.ui.Modal):
    def __init__(self, target_idx, od, is_admin_request=False): 
        super().__init__(title="ระบุเหตุผลการยกเลิก")
        self.target_idx, self.od = target_idx, od
        self.is_admin_request = is_admin_request 
        self.reason = discord.ui.TextInput(label='เหตุผลที่ยกเลิก', placeholder='ระบุเหตุผลที่นี่...', style=discord.TextStyle.paragraph, required=True)
        self.add_item(self.reason)
    
    async def on_submit(self, it: discord.Interaction):
        await it.response.defer(ephemeral=True)
        gid = str(it.guild.id) # ระบุ ID เซิร์ฟเวอร์
        
        # แก้ Logic: โหลดและบันทึกแยกไฟล์ตาม Guild ID
        d = load_data(gid, "leaves", []) 
        if 0 <= self.target_idx < len(d):
            old_data = d.pop(self.target_idx)
            save_data(gid, "leaves", d)
            await update_summary_board(it.guild)
            
            cfg = load_data(gid, "config", {}) # โหลด Config ของ Guild นี้
            log_ch_id = cfg.get("log_ch")
            if log_ch_id:
                log_ch = bot.get_channel(int(log_ch_id))
                if log_ch:
                    # --- [เพิ่ม Logic ตรวจสอบผู้ดำเนินการ โดยไม่เปลี่ยนคำเดิม] ---
                    u_id = str(it.user.id)
                    target_uid = old_data['target_id']
                    executor_name = it.user.display_name
                    
                    # ตรวจสอบว่าเป็น Admin หรือ เป็นการยกเลิกแทนเพื่อน
                    if self.is_admin_request:
                        executor_txt = f"**👮 ผู้ดำเนินการ:** {executor_name} (Admin)\n\n"
                    elif u_id != target_uid:
                        executor_txt = f"**👤 ผู้ดำเนินการ (ยกเลิกแทน):** {executor_name}\n\n"
                    else:
                        executor_txt = "" # ถ้าเจ้าของยกเลิกเอง ไม่ต้องแสดงบรรทัดนี้

                    log_title = "📌 บันทึกการจัดการโดยผู้ดูแล (ยกเลิกใบลา)" if self.is_admin_request else "📌 บันทึกยกเลิกการแจ้งลา"
                    log_color = 0xe67e22 if self.is_admin_request else 0xe74c3c 
                    note_label = "หมายเหตุจากแอดมิน" if self.is_admin_request else "หมายเหตุ"
                    
                    target_member = it.guild.get_member(int(old_data['target_id']))
                    tn = target_member.display_name if target_member else old_data['name']
                    dr = old_data['start_date'] if old_data['start_date'] == old_data['end_date'] else f"{old_data['start_date']} - {old_data['end_date']}"
                    
                    log_em = discord.Embed(title=log_title, color=log_color)
                    log_em.description = (
                        f"**👤 สมาชิกที่ลา:** {tn}\n\n"
                        f"{executor_txt}" # แทรก Logic ผู้ดำเนินการตรงนี้ โดยคำอื่นยังอยู่ครบ
                        f"**📝 รายละเอียดรายการที่ถูกยกเลิก:**\n"
                        f" • **วันที่ลา:** {dr} `({old_data.get('total_days', 1)} วัน)`\n"
                        f" • **ประเภท:** {old_data.get('leave_category', 'ทั่วไป')}\n"
                        f" • **เหตุผลเดิม:** {old_data.get('reason', '-')}\n\n"
                        f"**🛑 {note_label}:** {self.reason.value}\n\n"
                        f"{LONG_SEP}"
                    )
                    log_em.set_footer(text=f"บันทึกเมื่อ: {get_thai_time().strftime('%d/%m/%Y %H:%M:%S')}")
                    await log_ch.send(embed=log_em)
            
            await it.edit_original_response(content=f"❌ ยกเลิกรายการแจ้งลาเรียบร้อยแล้ว!", view=None)
            await asyncio.sleep(3)
            try: await it.delete_original_response()
            except: pass

class ConfirmCancelView(discord.ui.View):
    def __init__(self, target_idx, od):
        super().__init__(timeout=60)
        self.target_idx, self.od = target_idx, od

    @discord.ui.button(label="✅ ยืนยันการยกเลิก", style=discord.ButtonStyle.success)
    async def confirm(self, it: discord.Interaction, b: discord.ui.Button):
        # ส่งค่า False เพื่อบอกว่าเป็นรายการจากสมาชิกปกติ (คงคำพูดเดิม)
        await it.response.send_modal(CancelReasonModal(self.target_idx, self.od, is_admin_request=False))

    @discord.ui.button(label="❌ ไม่ยกเลิกแล้ว", style=discord.ButtonStyle.danger)
    async def cancel(self, it: discord.Interaction, b: discord.ui.Button):
        await it.response.defer()
        try:
            await it.delete_original_response()
        except:
            pass

class CancelSelect(discord.ui.Select):
    def __init__(self, opts):
        super().__init__(placeholder="📋 เลือกรายการที่จะยกเลิก...", options=opts)
    async def callback(self, it: discord.Interaction):
        await it.response.defer(ephemeral=True)
        gid = str(it.guild.id) # เพิ่ม Logic ระบุ Guild
        idx = int(self.values[0])
        d = load_data(gid, "leaves", []) # เปลี่ยนมาใช้ load_data
        if 0 <= idx < len(d):
            od = d[idx]
            dr = od['start_date'] if od['start_date'] == od['end_date'] else f"{od['start_date']} - {od['end_date']}"
            txt = f"⚠️ **แน่ใจหรือไม่ที่จะยกเลิกการลานี้?**\n👤 **คนลา:** <@{od['target_id']}>\n📝 **ประเภท:** `{od.get('leave_category','ทั่วไป')}`\n📅 **วันที่:** {dr} `({od.get('total_days', 1)} วัน)`"
            await it.edit_original_response(content=txt, view=ConfirmCancelView(idx, od))

# --- 7. ระบบแก้ไขวันสิ้นสุด (ปรับตามสั่ง: ตัดพิมพ์เอง / หัวข้อใหม่ / อีโมจิปฏิทิน / Modal เหตุผล) ---
async def process_edit_leave(it, idx, od, new_end_str, edit_reason="-"):
    gid = str(it.guild.id) # ระบุ ID เซิร์ฟเวอร์
    d = load_data(gid, "leaves", []) # โหลดข้อมูลของ Guild นี้
    old_e = od['end_date']
    
    if 0 <= idx < len(d):
        old_days = (datetime.strptime(old_e, "%d/%m/%Y") - datetime.strptime(od['start_date'], "%d/%m/%Y")).days + 1
        new_days = (datetime.strptime(new_end_str, "%d/%m/%Y") - datetime.strptime(od['start_date'], "%d/%m/%Y")).days + 1
        diff = new_days - old_days
        diff_txt = f"เพิ่มขึ้น {diff} วัน" if diff > 0 else f"ลดลง {abs(diff)} วัน" if diff < 0 else "เท่าเดิม"

        d[idx]['end_date'] = new_end_str
        d[idx]['total_days'] = new_days
        save_data(gid, "leaves", d) # บันทึกแยกไฟล์ตาม Guild ID
        await update_summary_board(it.guild)
        
        cfg = load_data(gid, "config", {}) # โหลด Config ของ Guild นี้
        log_ch_id = cfg.get("log_ch")
        if log_ch_id:
            log_ch = bot.get_channel(int(log_ch_id))
            if log_ch:
                u_id = str(it.user.id)
                has_admin_role = any(r.name in ["Admin", "ผู้ดูแล"] for r in it.user.roles)
                is_involved = u_id == od['target_id'] or u_id == od['user_id']
                is_admin_action = has_admin_role and not is_involved
                
                log_title = "📌 บันทึกการจัดการโดยผู้ดูแล" if is_admin_action else "📌 บันทึกการแก้ไขวันสิ้นสุดการลา"
                log_color = 0xe67e22 if is_admin_action else 0x95a5a6
                
                target_member = it.guild.get_member(int(od['target_id']))
                target_name = target_member.display_name if target_member else od['name']
                executor_name = it.user.display_name
                
                log_em = discord.Embed(title=log_title, color=log_color)
                on_behalf = f"\n**👮 ผู้แจ้งแก้ไขแทน:** {executor_name} (Admin)" if is_admin_action else f"\n**👤 ผู้แจ้งแก้ไขแทน:** {executor_name}" if u_id != od['target_id'] else ""
                
                log_em.description = (
                    f"**👤 สมาชิกที่ลา:** {target_name}{on_behalf}\n\n"
                    f"**📝 ประเภท:** {od.get('leave_category', 'ทั่วไป')}\n"
                    f"**📅 วันที่ลาเดิม:** {od['start_date']} - {old_e} `({old_days} วัน)`\n"
                    f"**📅 วันที่ลาใหม่:** {od['start_date']} - {new_end_str} `({new_days} วัน)`\n"
                    f"**📈 การเปลี่ยนแปลง:** `{diff_txt}`\n"
                    f"**💬 เหตุผลเดิมที่แจ้ง:** {od.get('reason', '-')}\n"
                    f"**🛑 เหตุผลที่ขอแก้ไข:** {edit_reason}\n\n"
                    f"{LONG_SEP}"
                )
                log_em.set_footer(text=f"บันทึกเมื่อ: {get_thai_time().strftime('%d/%m/%Y %H:%M')} น.")
                await log_ch.send(embed=log_em) 
        
        # 3. จัดการปิดข้อความลับ (เพิ่มการ Delete เพื่อให้หายไปเอง)
        try:
            await it.edit_original_response(content=f"✅ แก้ไขวันสิ้นสุดเป็นวันที่ `{new_end_str}` เรียบร้อยแล้ว!", embed=None, view=None)
            await asyncio.sleep(3)
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
    async def retry(self, it: discord.Interaction, b: discord.ui.Button):
        # ย้อนกลับไปหน้าเลือกวันที่สิ้นสุดใหม่ (คงคำพูดเดิม)
        await it.response.edit_message(
            content="📅 **เลือกวันที่สิ้นสุดใหม่อีกครั้ง:**", 
            embed=None, 
            view=SubMenuView(it, EditDateSelect(self.idx, self.od, it))
        )
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
        
        # ตรวจสอบรูปแบบวันที่ (คงคำพูดเดิม)
        if not validate_date(val):
            return await it.response.send_message("❌ รูปแบบวันที่ไม่ถูกต้อง หรือไม่ใช่ปี ค.ศ.!", view=EditRetryView(self.idx, self.od, self.parent_it), ephemeral=True)
        
        s_dt = datetime.strptime(self.od['start_date'], "%d/%m/%Y")
        e_dt = datetime.strptime(val, "%d/%m/%Y")
        
        # ตรวจสอบเงื่อนไขวันที่ (คงคำพูดเดิม)
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
        
        # แสดง Embed ตรวจสอบข้อมูล (คงคำพูดเดิม)
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
    async def confirm(self, it: discord.Interaction, b: discord.ui.Button):
        # เรียก Modal เพื่อขอเหตุผลก่อนบันทึก (คงโครงสร้างเดิม)[cite: 1]
        await it.response.send_modal(EditReasonModal(self.idx, self.od, self.new_end))

    @discord.ui.button(label="📅 เลือกวันใหม่", style=discord.ButtonStyle.primary)
    async def reselect(self, it: discord.Interaction, b: discord.ui.Button):
        # ย้อนกลับไปหน้าเลือกวันที่สิ้นสุดใหม่ (คงคำพูดเดิม)[cite: 1]
        await it.response.edit_message(content="📅 **กรุณาเลือกวันที่สิ้นสุดใหม่อีกครั้ง:**", embed=None, view=SubMenuView(it, EditDateSelect(self.idx, self.od, it)))

    @discord.ui.button(label="❌ ยกเลิก", style=discord.ButtonStyle.danger)
    async def cancel(self, it: discord.Interaction, b: discord.ui.Button):
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
    async def callback(self, it: discord.Interaction):
        await it.response.defer(ephemeral=True)
        gid = str(it.guild.id) # เพิ่ม Logic ระบุ Guild
        idx = int(self.values[0])
        d = load_data(gid, "leaves", []) # เปลี่ยนมาใช้ load_data
        if 0 <= idx < len(d):
            await it.edit_original_response(content="📅 **เลือกวันที่สิ้นสุดใหม่:**", view=SubMenuView(it, EditDateSelect(idx, d[idx], it)))

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
    async def l_cn(self, it: discord.Interaction, b: discord.ui.Button):
        # --- เริ่มการแก้ไข Logic แยกไฟล์ตาม Guild ---
        gid = str(it.guild.id)
        d = load_data(gid, "leaves", []) # โหลดข้อมูลใบลาของเซิร์ฟเวอร์นี้
        
        u_id, now_date, opts = str(it.user.id), get_thai_time().date(), []
        
        for i, e in enumerate(d):
            # เงื่อนไขเดิม: แสดงเฉพาะใบลาที่ตนเองมีส่วนเกี่ยวข้อง
            if e['user_id'] == u_id or e['target_id'] == u_id:
                try:
                    if datetime.strptime(e['end_date'], "%d/%m/%Y").date() < now_date: continue
                except: continue
                
                target_member = it.guild.get_member(int(e['target_id']))
                tn = target_member.display_name if target_member else e['name']
                dr = e['start_date'] if e['start_date'] == e['end_date'] else f"{e['start_date']} - {e['end_date']}"
                
                # คงคำพูดและ Emoji เดิมของคุณไว้ทั้งหมด
                opts.append(discord.SelectOption(
                    label=f"{tn} | {dr} ({e.get('total_days', 1)} วัน)",
                    description=f"ประเภท: {e.get('leave_category','ทั่วไป')} | เหตุผล: {e.get('reason','-')[:20]}...",
                    value=str(i)
                ))
        
        if not opts: 
            return await it.response.send_message("❌ ไม่พบรายการที่คุณสามารถยกเลิกได้", ephemeral=True)
            
        await it.response.send_message("📋 เลือกใบลาของคุณที่จะยกเลิก:", view=SubMenuView(it, CancelSelect(opts[:25])), ephemeral=True)
  
    @discord.ui.button(label="✏️ แก้ไขวันลา", style=discord.ButtonStyle.danger, custom_id="v_l_final_vMaster_DMD_master_4")
    async def l_ed(self, it: discord.Interaction, b: discord.ui.Button):
        # --- เริ่มการแก้ไข Logic แยกไฟล์ตาม Guild ---[cite: 1]
        gid = str(it.guild.id)
        d = load_data(gid, "leaves", []) # โหลดข้อมูลใบลาของเซิร์ฟเวอร์นี้[cite: 1]
        
        u_id, now_date, opts = str(it.user.id), get_thai_time().date(), []

        for i, e in enumerate(d):
            # เงื่อนไขเดิม: ต้องเกี่ยวข้อง และเป็นการลามากกว่า 1 วัน[cite: 1]
            if (e['user_id'] == u_id or e['target_id'] == u_id) and e['start_date'] != e['end_date']:
                try:
                    if datetime.strptime(e['end_date'], "%d/%m/%Y").date() < now_date: continue
                except: continue
                
                target_member = it.guild.get_member(int(e['target_id']))
                tn = target_member.display_name if target_member else e['name']
                dr = e['start_date'] if e['start_date'] == e['end_date'] else f"{e['start_date']} - {e['end_date']}"
                
                # คงคำพูดและ Emoji เดิมของคุณไว้ทั้งหมด[cite: 1]
                opts.append(discord.SelectOption(
                    label=f"{tn} | {dr} ({e.get('total_days', 1)} วัน)",
                    description=f"ประเภท: {e.get('leave_category','ทั่วไป')} | เหตุผล: {e.get('reason','-')[:20]}...",
                    value=str(i)
                ))
        
        if not opts: 
            return await it.response.send_message("❌ ไม่พบรายการที่คุณสามารถแก้ไขได้", ephemeral=True)
            
        await it.response.send_message("✏️ เลือกใบลาของคุณที่จะแก้ไข:", view=SubMenuView(it, EditLeaveSelect(opts[:25], it)), ephemeral=True)   


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


# --- 9. ระบบ Backup (แก้ไขให้ส่งเฉพาะคนกด และแยกไฟล์ตาม Guild) ---
@bot.command()
@commands.has_any_role("Admin", "ผู้ดูแล")
async def backup(ctx):
    # แก้ไข Logic: ระบุ Path ไฟล์ของเซิร์ฟเวอร์ปัจจุบัน
    gid = str(ctx.guild.id)
    path_leaves = get_path(gid, "leaves")
    path_config = get_path(gid, "config")
    
    # แก้ไข Logic: ส่ง DM เฉพาะหา ctx.author (คนพิมพ์คำสั่ง) เท่านั้น
    try:
        f_send = []
        if os.path.exists(path_leaves): f_send.append(discord.File(path_leaves))
        if os.path.exists(path_config): f_send.append(discord.File(path_config))
        
        if not f_send:
            return await ctx.send("❌ **ไม่พบไฟล์ข้อมูลในเซิร์ฟเวอร์นี้เพื่อทำ Backup**")
            
        await ctx.author.send(f"📦 นี่คือไฟล์ Backup ข้อมูลและการตั้งค่าของเซิร์ฟเวอร์ **{ctx.guild.name}** ครับ:", files=f_send)
        await ctx.send(f"✅ ส่งไฟล์ Backup เข้า DM ของท่าน (@{ctx.author.display_name}) เรียบร้อยแล้ว")
    except discord.Forbidden:
        await ctx.send("❌ **ไม่สามารถส่งไฟล์ได้!** โปรดเปิดการรับข้อความจาก DM (Private Message) ก่อนครับ")

# --- ย้าย on_ready มาไว้ท้ายสุด และใส่ add_view ให้ครบ ---
@bot.event
async def on_ready():
    # ลงทะเบียน View ทั้งหมดเพื่อให้ปุ่มทำงานได้ตลอดกาล (Persistent Views)
    bot.add_view(LeaveMainView())         # หน้าหลักแจ้งลา
    bot.add_view(RealtimeRefreshView())    # ปุ่มรีเฟรชบอร์ด
    bot.add_view(AdminPanelView())         # หน้าหลัก !admin
    bot.add_view(CategorySelectionView())  # หน้าเลือกหมวดหมู่ (แจ้งลา/แจ้งปรับเงิน)
    bot.add_view(AdminLeaveManagementView()) # ระบบลา/จัดการใบลา
    bot.add_view(ConfirmClearView())       # หน้ากดยืนยัน Cleanup 30 วัน
    
    print(f'✅ {bot.user.name} ออนไลน์เรียบร้อย | ระบบปี 2026 พร้อมใช้งาน')
    if not daily_report_task.is_running(): daily_report_task.start()
    if not weekly_report_task.is_running(): weekly_report_task.start()

bot.run(TOKEN)