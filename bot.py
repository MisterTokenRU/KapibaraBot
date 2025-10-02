import discord
from discord.ext import commands, tasks
from discord import ui
import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка интентов
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Конфигурация (ЗАМЕНИТЕ НА РЕАЛЬНЫЕ ID ВАШЕГО СЕРВЕРА)
MODERATOR_ROLE_ID = 123456789012345678  # ID роли модератора
LOG_CHANNEL_ID = 1422205051153154118     # ID канала для логов
PENDING_REQUESTS_CHANNEL_ID = 1422205095755645129  # ID канала для заявок
STATS_CHANNEL_ID = 1422222709047300136   # ID канала для статистики

# Словарь с ролями по отделам (ЗАМЕНИТЕ НА РЕАЛЬНЫЕ ID РОЛЕЙ)
ROLES_BY_ORGANIZATION = {
    "Academy": [1409626655630168312],
    "Police Academy": [1409626656150388837],
    "MD": [1409626656150388836],
    "Офицер Полиции": [1409626656150388835]
}

# Хранилища данных
pending_requests = {}
stat_requests = {}

class OrganizationSelect(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Academy", 
                description="Роли для Academy",
                emoji="🏢"
            ),
            discord.SelectOption(
                label="PA", 
                description="Роли для Police Academy",
                emoji="🏛️"
            ),
            discord.SelectOption(
                label="MD", 
                description="Роли для MD",
                emoji="🏬"
            ),
            discord.SelectOption(
                label="Офицер Полиции", 
                description="Для Офицера Полиции",
                emoji="🧪"
            ),
        ]
        super().__init__(
            placeholder="Выберите отдел",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="organization_select"
        )

    async def callback(self, interaction: discord.Interaction):
        selected_org = self.values[0]
        user = interaction.user
        
        # Проверяем, нет ли уже pending заявки у пользователя
        if user.id in pending_requests:
            await interaction.response.send_message(
                "❌ У вас уже есть активная заявка на рассмотрении!",
                ephemeral=True
            )
            return
        
        # Создаем заявку
        request_id = f"{user.id}_{int(datetime.now().timestamp())}"
        pending_requests[user.id] = {
            'request_id': request_id,
            'user_id': user.id,
            'username': str(user),
            'organization': selected_org,
            'timestamp': datetime.now(),
            'status': 'pending'
        }
        
        # Отправляем заявку модераторам
        await self.send_moderation_request(interaction, user, selected_org, request_id)
        
        # Ответ пользователю
        embed = discord.Embed(
            title="📨 Заявка отправлена!",
            description=f"Ваша заявка на получение ролей **{selected_org}** отправлена на модерацию.",
            color=0xffff00
        )
        embed.add_field(
            name="Статус",
            value="⏳ Ожидает рассмотрения модератором",
            inline=False
        )
        embed.add_field(
            name="Что дальше?",
            value="Ожидайте уведомления о решении по вашей заявке.",
            inline=False
        )
        embed.set_footer(text=f"ID заявки: {request_id}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def send_moderation_request(self, interaction, user, organization, request_id):
        """Отправляет заявку на модерацию"""
        guild = interaction.guild
        mod_channel = guild.get_channel(PENDING_REQUESTS_CHANNEL_ID)
        
        if not mod_channel:
            return
        
        embed = discord.Embed(
            title="🆕 Новая заявка на роль",
            color=0x00ffff,
            timestamp=datetime.now()
        )
        embed.add_field(name="👤 Пользователь", value=f"{user.mention}\n{user}", inline=True)
        embed.add_field(name="🏢 Отдел", value=organization, inline=True)
        embed.add_field(name="📅 Дата подачи", value=datetime.now().strftime("%d.%m.%Y %H:%M"), inline=True)
        embed.add_field(name="🆔 ID заявки", value=request_id, inline=False)
        
        # Добавляем базовую статистику
        join_date = user.joined_at.strftime("%d.%m.%Y") if user.joined_at else "Неизвестно"
        account_age = (datetime.now().replace(tzinfo=None) - user.created_at.replace(tzinfo=None)).days
        embed.add_field(
            name="📊 Базовая информация", 
            value=f"На сервере с: {join_date}\nАккаунту: {account_age} дней", 
            inline=False
        )
        
        view = ModerationView(request_id, user.id, organization)
        
        message = await mod_channel.send(
            content=f"<@&{MODERATOR_ROLE_ID}> Новая заявка на рассмотрение!",
            embed=embed,
            view=view
        )
        
        # Сохраняем ID сообщения для дальнейшего обновления
        pending_requests[user.id]['message_id'] = message.id

class ModerationView(ui.View):
    def __init__(self, request_id, user_id, organization):
        super().__init__(timeout=None)
        self.request_id = request_id
        self.user_id = user_id
        self.organization = organization

    @ui.button(label="✅ Одобрить", style=discord.ButtonStyle.success, custom_id="approve")
    async def approve_button(self, interaction: discord.Interaction, button: ui.Button):
        # Проверяем права модератора
        if not await self.check_moderator(interaction):
            return
        
        user = interaction.guild.get_member(self.user_id)
        if not user:
            await interaction.response.send_message("❌ Пользователь не найден на сервере!", ephemeral=True)
            return
        
        # Выдаем роли
        if self.organization in ROLES_BY_ORGANIZATION:
            added_roles = []
            for role_id in ROLES_BY_ORGANIZATION[self.organization]:
                role = interaction.guild.get_role(role_id)
                if role:
                    await user.add_roles(role)
                    added_roles.append(role.mention)
            
            # Обновляем статус заявки
            if self.user_id in pending_requests:
                pending_requests[self.user_id]['status'] = 'approved'
                pending_requests[self.user_id]['moderator'] = str(interaction.user)
                pending_requests[self.user_id]['processed_at'] = datetime.now()
            
            # Обновляем сообщение заявки
            embed = interaction.message.embeds[0]
            embed.color = 0x00ff00
            embed.add_field(name="✅ Статус", value="Одобрено", inline=True)
            embed.add_field(name="👮 Модератор", value=interaction.user.mention, inline=True)
            embed.add_field(name="⏰ Время обработки", value=datetime.now().strftime("%H:%M"), inline=True)
            
            # Отключаем кнопки
            for item in self.children:
                item.disabled = True
            
            await interaction.message.edit(embed=embed, view=self)
            
            # Уведомляем пользователя
            try:
                user_embed = discord.Embed(
                    title="✅ Заявка одобрена!",
                    description=f"Ваша заявка на организацию **{self.organization}** была одобрена.",
                    color=0x00ff00
                )
                if added_roles:
                    user_embed.add_field(
                        name="Выданные роли:",
                        value="\n".join(added_roles),
                        inline=False
                    )
                user_embed.add_field(
                    name="Модератор",
                    value=interaction.user.mention,
                    inline=True
                )
                user_embed.set_footer(text="Приятного времяпрепровождения на сервере!")
                
                await user.send(embed=user_embed)
            except:
                pass  # Если ЛС закрыты
            
            await interaction.response.send_message("✅ Заявка одобрена!", ephemeral=True)
            
            # Логируем действие
            await self.log_action(interaction, "approved", user)
            
            # Отправляем статистику в канал статистики
            await self.send_stats_to_channel(interaction, user, "approved")
            
        else:
            await interaction.response.send_message("❌ Отдел не найден!", ephemeral=True)

    @ui.button(label="❌ Отклонить", style=discord.ButtonStyle.danger, custom_id="reject")
    async def reject_button(self, interaction: discord.Interaction, button: ui.Button):
        # Проверяем права модератора
        if not await self.check_moderator(interaction):
            return
        
        user = interaction.guild.get_member(self.user_id)
        
        # Обновляем статус заявки
        if self.user_id in pending_requests:
            pending_requests[self.user_id]['status'] = 'rejected'
            pending_requests[self.user_id]['moderator'] = str(interaction.user)
            pending_requests[self.user_id]['processed_at'] = datetime.now()
        
        # Обновляем сообщение заявки
        embed = interaction.message.embeds[0]
        embed.color = 0xff0000
        embed.add_field(name="❌ Статус", value="Отклонено", inline=True)
        embed.add_field(name="👮 Модератор", value=interaction.user.mention, inline=True)
        embed.add_field(name="⏰ Время обработки", value=datetime.now().strftime("%H:%M"), inline=True)
        
        # Отключаем кнопки
        for item in self.children:
            item.disabled = True
        
        await interaction.message.edit(embed=embed, view=self)
        
        # Уведомляем пользователя
        try:
            user_embed = discord.Embed(
                title="❌ Заявка отклонена",
                description=f"Ваша заявка на организацию **{self.organization}** была отклонена модератором.",
                color=0xff0000
            )
            user_embed.add_field(
                name="Причина",
                value="По всем вопросам обращайтесь к администрации сервера.",
                inline=False
            )
            await user.send(embed=user_embed)
        except:
            pass  # Если ЛС закрыты
        
        await interaction.response.send_message("❌ Заявка отклонена!", ephemeral=True)
        
        # Логируем действие
        await self.log_action(interaction, "rejected", user)
        
        # Отправляем статистику в канал статистики
        await self.send_stats_to_channel(interaction, user, "rejected")

    @ui.button(label="📊 Запросить статистику", style=discord.ButtonStyle.primary, custom_id="request_stats")
    async def request_stats_button(self, interaction: discord.Interaction, button: ui.Button):
        # Проверяем права модератора
        if not await self.check_moderator(interaction):
            return
        
        user = interaction.guild.get_member(self.user_id)
        if not user:
            await interaction.response.send_message("❌ Пользователь не найден на сервере!", ephemeral=True)
            return
        
        # Создаем запрос статистики
        stat_request_id = f"stat_{self.user_id}_{int(datetime.now().timestamp())}"
        stat_requests[stat_request_id] = {
            'moderator_id': interaction.user.id,
            'user_id': self.user_id,
            'timestamp': datetime.now(),
            'request_id': self.request_id,
            'organization': self.organization
        }
        
        # Отправляем запрос пользователю
        try:
            stats_view = UserStatsView(stat_request_id, interaction.user)
            
            stats_embed = discord.Embed(
                title="📊 Запрос статистики",
                description="Модератор запросил дополнительную информацию для рассмотрения вашей заявки.",
                color=0x0099ff
            )
            stats_embed.add_field(
                name="Что нужно сделать?",
                value="Пожалуйста, предоставьте дополнительную информацию о себе, нажав на кнопку ниже.",
                inline=False
            )
            stats_embed.add_field(
                name="Модератор",
                value=interaction.user.mention,
                inline=True
            )
            stats_embed.add_field(
                name="Заявка",
                value=self.organization,
                inline=True
            )
            stats_embed.set_footer(text="Эта информация поможет нам быстрее обработать вашу заявку")
            
            await user.send(embed=stats_embed, view=stats_view)
            
            # Обновляем сообщение заявки
            embed = interaction.message.embeds[0]
            embed.add_field(
                name="📊 Статистика",
                value="✅ Запрос отправлен пользователю",
                inline=True
            )
            await interaction.message.edit(embed=embed)
            
            await interaction.response.send_message(
                f"✅ Запрос статистики отправлен пользователю {user.mention}!",
                ephemeral=True
            )
            
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Не удалось отправить запрос пользователю: {str(e)}",
                ephemeral=True
            )

    async def check_moderator(self, interaction):
        """Проверяет, является ли пользователь модератором"""
        moderator_role = interaction.guild.get_role(MODERATOR_ROLE_ID)
        if moderator_role not in interaction.user.roles:
            await interaction.response.send_message(
                "❌ У вас нет прав для модерации заявок!",
                ephemeral=True
            )
            return False
        return True

    async def log_action(self, interaction, action, target_user):
        """Логирует действия модераторов"""
        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="📝 Лог модерации",
                color=0x7289da,
                timestamp=datetime.now()
            )
            embed.add_field(name="Действие", value="Одобрено" if action == "approved" else "Отклонено", inline=True)
            embed.add_field(name="Модератор", value=interaction.user.mention, inline=True)
            embed.add_field(name="Пользователь", value=target_user.mention, inline=True)
            embed.add_field(name="Отдел", value=self.organization, inline=True)
            embed.add_field(name="ID заявки", value=self.request_id, inline=False)
            
            await log_channel.send(embed=embed)

    async def send_stats_to_channel(self, interaction, user, action):
        """Отправляет статистику в канал статистики"""
        stats_channel = interaction.guild.get_channel(STATS_CHANNEL_ID)
        if not stats_channel:
            return
        
        # Собираем статистику пользователя
        join_date = user.joined_at.strftime("%d.%m.%Y %H:%M") if user.joined_at else "Неизвестно"
        account_created = user.created_at.strftime("%d.%m.%Y")
        account_age = (datetime.now().replace(tzinfo=None) - user.created_at.replace(tzinfo=None)).days
        server_age = (datetime.now().replace(tzinfo=None) - user.joined_at.replace(tzinfo=None)).days if user.joined_at else 0
        
        # Считаем количество ролей (исключая @everyone)
        role_count = len([role for role in user.roles if role.name != "@everyone"])
        
        embed = discord.Embed(
            title=f"📈 Статистика заявки - {action.upper()}",
            color=0x00ff00 if action == "approved" else 0xff0000,
            timestamp=datetime.now()
        )
        
        embed.add_field(name="👤 Пользователь", value=f"{user.mention}\n{user}", inline=True)
        embed.add_field(name="🏢 Отдел", value=self.organization, inline=True)
        embed.add_field(name="📊 Решение", value="✅ Одобрено" if action == "approved" else "❌ Отклонено", inline=True)
        
        embed.add_field(name="📅 На сервере с", value=join_date, inline=True)
        embed.add_field(name="📅 Аккаунт создан", value=account_created, inline=True)
        embed.add_field(name="🕒 Возраст аккаунта", value=f"{account_age} дней", inline=True)
        
        embed.add_field(name="👮 Модератор", value=interaction.user.mention, inline=True)
        embed.add_field(name="🎭 Количество ролей", value=role_count, inline=True)
        embed.add_field(name="🆔 ID заявки", value=self.request_id, inline=True)
        
        if action == "approved":
            # Добавляем информацию о выданных ролях
            role_names = []
            for role_id in ROLES_BY_ORGANIZATION[self.organization]:
                role = interaction.guild.get_role(role_id)
                if role:
                    role_names.append(role.name)
            
            if role_names:
                embed.add_field(
                    name="✅ Выданные роли",
                    value=", ".join(role_names),
                    inline=False
                )
        
        await stats_channel.send(embed=embed)

class UserStatsView(ui.View):
    def __init__(self, stat_request_id, moderator):
        super().__init__(timeout=3600)  # 1 час таймаут
        self.stat_request_id = stat_request_id
        self.moderator = moderator

    @ui.button(label="📋 Предоставить информацию", style=discord.ButtonStyle.primary)
    async def provide_info_button(self, interaction: discord.Interaction, button: ui.Button):
        # Создаем модальное окно для ввода информации
        modal = UserStatsModal(self.stat_request_id, self.moderator)
        await interaction.response.send_modal(modal)

class UserStatsModal(ui.Modal, title='📊 Дополнительная информация'):
    def __init__(self, stat_request_id, moderator):
        super().__init__()
        self.stat_request_id = stat_request_id
        self.moderator = moderator

    experience = ui.TextInput(
        label='Опыт в организации',
        placeholder='Опишите ваш опыт работы или участия в подобных отделах...',
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True
    )

    motivation = ui.TextInput(
        label='Цели и мотивация',
        placeholder='Почему вы хотите получить эти роли? Какие у вас цели?...',
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True
    )

    additional_info = ui.TextInput(
        label='Дополнительная информация',
        placeholder='Любая другая информация, которая может быть полезна...',
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Отправляем информацию модератору
        try:
            # Получаем информацию о запросе
            request_info = stat_requests.get(self.stat_request_id, {})
            
            # Отправляем модератору в ЛС
            mod_embed = discord.Embed(
                title="📊 Получена статистика от пользователя",
                color=0x00ff00,
                timestamp=datetime.now()
            )
            mod_embed.add_field(name="👤 Пользователь", value=interaction.user.mention, inline=True)
            mod_embed.add_field(name="📅 Время ответа", value=datetime.now().strftime("%H:%M"), inline=True)
            mod_embed.add_field(name="💼 Опыт", value=self.experience.value, inline=False)
            mod_embed.add_field(name="🎯 Мотивация", value=self.motivation.value, inline=False)
            
            if self.additional_info.value:
                mod_embed.add_field(name="📝 Дополнительно", value=self.additional_info.value, inline=False)
            
            try:
                await self.moderator.send(embed=mod_embed)
            except:
                # Если ЛС закрыты, ищем канал для заявок
                mod_channel = interaction.guild.get_channel(PENDING_REQUESTS_CHANNEL_ID)
                if mod_channel:
                    await mod_channel.send(
                        content=f"{self.moderator.mention}",
                        embed=mod_embed
                    )
            
            # Отправляем статистику в канал статистики
            await self.send_stats_to_channel(interaction, request_info)
            
            # Подтверждаем пользователю
            confirm_embed = discord.Embed(
                title="✅ Информация отправлена!",
                description="Спасибо за предоставленную информацию. Модератор получил ваши ответы и рассмотрит заявку в ближайшее время.",
                color=0x00ff00
            )
            await interaction.response.send_message(embed=confirm_embed, ephemeral=True)
            
            # Удаляем запрос из хранилища
            if self.stat_request_id in stat_requests:
                del stat_requests[self.stat_request_id]
                
        except Exception as e:
            await interaction.response.send_message(
                "❌ Произошла ошибка при отправке информации. Попробуйте позже.",
                ephemeral=True
            )

    async def send_stats_to_channel(self, interaction, request_info):
        """Отправляет статистику в канал статистики"""
        stats_channel = interaction.guild.get_channel(STATS_CHANNEL_ID)
        if not stats_channel:
            return
        
        user = interaction.user
        join_date = user.joined_at.strftime("%d.%m.%Y %H:%M") if user.joined_at else "Неизвестно"
        account_age = (datetime.now().replace(tzinfo=None) - user.created_at.replace(tzinfo=None)).days
        
        embed = discord.Embed(
            title="📊 Получена статистика от пользователя",
            color=0x0099ff,
            timestamp=datetime.now()
        )
        
        embed.add_field(name="👤 Пользователь", value=f"{user.mention}\n{user}", inline=True)
        embed.add_field(name="🏢 Отдел", value=request_info.get('organization', 'Неизвестно'), inline=True)
        embed.add_field(name="📅 На сервере с", value=join_date, inline=True)
        
        embed.add_field(name="💼 Опыт", value=self.experience.value, inline=False)
        embed.add_field(name="🎯 Мотивация", value=self.motivation.value, inline=False)
        
        if self.additional_info.value:
            embed.add_field(name="📝 Дополнительная информация", value=self.additional_info.value, inline=False)
        
        embed.add_field(name="👮 Запросил модератор", value=self.moderator.mention, inline=True)
        embed.add_field(name="🆔 ID запроса", value=self.stat_request_id, inline=True)
        
        await stats_channel.send(embed=embed)

class RemoveRolesButton(ui.Button):
    def __init__(self):
        super().__init__(
            label="Снять роли",
            style=discord.ButtonStyle.danger,
            custom_id="remove_roles"
        )

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user
        removed_roles = []
        
        # Удаляем все роли организаций
        for org_roles in ROLES_BY_ORGANIZATION.values():
            for role_id in org_roles:
                role = interaction.guild.get_role(role_id)
                if role and role in user.roles:
                    await user.remove_roles(role)
                    removed_roles.append(role.name)
        
        if removed_roles:
            embed = discord.Embed(
                title="✅ Роли сняты!",
                description="Все роли организаций были удалены.",
                color=0xffa500
            )
            embed.add_field(
                name="Снятые роли:",
                value="\n".join(removed_roles),
                inline=False
            )
            
            # Отправляем в канал статистики
            stats_channel = interaction.guild.get_channel(STATS_CHANNEL_ID)
            if stats_channel:
                stats_embed = discord.Embed(
                    title="🗑️ Пользователь снял роли",
                    color=0xffa500,
                    timestamp=datetime.now()
                )
                stats_embed.add_field(name="👤 Пользователь", value=f"{user.mention}\n{user}", inline=True)
                stats_embed.add_field(name="📅 Время", value=datetime.now().strftime("%d.%m.%Y %H:%M"), inline=True)
                stats_embed.add_field(name="🎭 Снятые роли", value=", ".join(removed_roles), inline=False)
                await stats_channel.send(embed=stats_embed)
                
        else:
            embed = discord.Embed(
                title="ℹ️ Роли не найдены",
                description="У вас не было активных ролей организаций.",
                color=0xffff00
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

class CancelButton(ui.Button):
    def __init__(self):
        super().__init__(
            label="Отменить запрос",
            style=discord.ButtonStyle.secondary,
            custom_id="cancel_request"
        )

    async def callback(self, interaction: discord.Interaction):
        # Удаляем pending заявку если есть
        if interaction.user.id in pending_requests:
            request_data = pending_requests[interaction.user.id]
            del pending_requests[interaction.user.id]
            
            # Отправляем в канал статистики
            stats_channel = interaction.guild.get_channel(STATS_CHANNEL_ID)
            if stats_channel:
                embed = discord.Embed(
                    title="❌ Пользователь отменил заявку",
                    color=0xff0000,
                    timestamp=datetime.now()
                )
                embed.add_field(name="👤 Пользователь", value=f"{interaction.user.mention}\n{interaction.user}", inline=True)
                embed.add_field(name="🏢 Отдел", value=request_data['organization'], inline=True)
                embed.add_field(name="📅 Время подачи", value=request_data['timestamp'].strftime("%d.%m.%Y %H:%M"), inline=True)
                embed.add_field(name="⏰ Время отмены", value=datetime.now().strftime("%H:%M"), inline=True)
                await stats_channel.send(embed=embed)
        
        embed = discord.Embed(
            title="❌ Запрос отменен",
            description="Вы можете запросить роли позже.",
            color=0xff0000
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class RoleRequestView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(OrganizationSelect())
        self.add_item(RemoveRolesButton())
        self.add_item(CancelButton())

@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user.name} успешно запущен!')
    print(f'🆔 ID бота: {bot.user.id}')
    print(f'📊 Серверов: {len(bot.guilds)}')
    print('------')
    
    # Добавляем персистентное view
    bot.add_view(RoleRequestView())
    bot.add_view(ModerationView("init", 0, "init"))

@bot.command(name='настройка_ролей')
@commands.has_permissions(administrator=True)
async def setup_roles(ctx):
    """Команда для настройки системы ролей (только для администраторов)"""
    
    welcome_text = """# Добро пожаловать на канал #г-запрос-роли!

**Система выдачи ролей с модерацией**

Для запроса роли выберите вашу организацию ниже. 
Заявка будет отправлена на рассмотрение модераторам.

⏳ Время рассмотрения: обычно до 24 часов"""

    embed = discord.Embed(
        title="🎯 Система запроса ролей с модерацией",
        description=welcome_text,
        color=0x7289da
    )
    
    embed.add_field(
        name="📋 Как это работает:",
        value="1. 🏢 Выберите организацию из списка\n"
              "2. 📨 Заявка отправляется модераторам\n"
              "3. ⏳ Ожидайте рассмотрения (получите уведомление)\n"
              "4. ✅ При одобрении - роли будут выданы автоматически\n"
              "5. 🗑️ 'Снять роли' - удаляет все ваши роли организаций",
        inline=False
    )
    
    embed.set_footer(text="По всем вопросам обращайтесь к модераторам сервера")
    
    await ctx.send(embed=embed, view=RoleRequestView())
    await ctx.message.delete()

@bot.command(name='статистика')
@commands.has_permissions(administrator=True)
async def show_stats(ctx):
    """Показывает общую статистику системы"""
    pending_count = sum(1 for req in pending_requests.values() if req['status'] == 'pending')
    approved_count = sum(1 for req in pending_requests.values() if req['status'] == 'approved')
    rejected_count = sum(1 for req in pending_requests.values() if req['status'] == 'rejected')
    stat_requests_count = len(stat_requests)
    
    # Статистика по отделам
    org_stats = {}
    for request in pending_requests.values():
        org = request['organization']
        if org not in org_stats:
            org_stats[org] = {'total': 0, 'approved': 0, 'rejected': 0, 'pending': 0}
        org_stats[org]['total'] += 1
        org_stats[org][request['status']] += 1
    
    embed = discord.Embed(
        title="📈 Общая статистика системы",
        color=0x7289da,
        timestamp=datetime.now()
    )
    
    embed.add_field(name="⏳ Ожидают рассмотрения", value=pending_count, inline=True)
    embed.add_field(name="✅ Одобрено", value=approved_count, inline=True)
    embed.add_field(name="❌ Отклонено", value=rejected_count, inline=True)
    embed.add_field(name="📊 Активных запросов статистики", value=stat_requests_count, inline=True)
    embed.add_field(name="📋 Всего заявок", value=len(pending_requests), inline=True)
    
    # Добавляем статистику по отделам
    if org_stats:
        org_text = ""
        for org, stats in list(org_stats.items())[:5]:  # Показываем первые 5
            org_text += f"**{org}**: {stats['total']} (✅{stats['approved']} ⏳{stats['pending']} ❌{stats['rejected']})\n"
        
        embed.add_field(name="🏢 Статистика по отделам", value=org_text, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='заявки')
@commands.has_permissions(administrator=True)
async def show_requests(ctx):
    """Показывает текущие pending заявки"""
    pending_count = sum(1 for req in pending_requests.values() if req['status'] == 'pending')
    stat_requests_count = len(stat_requests)
    
    embed = discord.Embed(
        title="📊 Статистика заявок",
        color=0x7289da
    )
    embed.add_field(name="⏳ Ожидают рассмотрения", value=pending_count, inline=True)
    embed.add_field(name="📋 Активных запросов статистики", value=stat_requests_count, inline=True)
    embed.add_field(name="📈 Всего активных заявок", value=len(pending_requests), inline=True)
    
    if pending_requests:
        pending_list = []
        for user_id, request in list(pending_requests.items())[:5]:
            if request['status'] == 'pending':
                user = ctx.guild.get_member(user_id)
                username = user.mention if user else request['username']
                time_ago = (datetime.now() - request['timestamp']).seconds // 60
                pending_list.append(f"{username} - {request['organization']} ({time_ago} мин. назад)")
        
        if pending_list:
            embed.add_field(
                name="📝 Последние заявки:",
                value="\n".join(pending_list),
                inline=False
            )
    
    await ctx.send(embed=embed)

# Фоновая задача для очистки старых данных
@tasks.loop(hours=24)
async def cleanup_old_data():
    """Очищает старые заявки и запросы статистики"""
    current_time = datetime.now().timestamp()
    removed_requests = 0
    removed_stats = 0
    
    # Очищаем старые заявки (старше 7 дней)
    for user_id in list(pending_requests.keys()):
        request = pending_requests[user_id]
        if request['timestamp'].timestamp() < current_time - (7 * 24 * 60 * 60):
            del pending_requests[user_id]
            removed_requests += 1
    
    # Очищаем старые запросы статистики (старше 24 часов)
    for stat_id in list(stat_requests.keys()):
        request = stat_requests[stat_id]
        if request['timestamp'].timestamp() < current_time - (24 * 60 * 60):
            del stat_requests[stat_id]
            removed_stats += 1
    
    # Логируем очистку
    if removed_requests > 0 or removed_stats > 0:
        print(f"🧹 Автоочистка: удалено {removed_requests} заявок и {removed_stats} запросов статистики")

@cleanup_old_data.before_loop
async def before_cleanup():
    await bot.wait_until_ready()

# Запускаем фоновую задачу при старте бота
@bot.event
async def on_connect():
    cleanup_old_data.start()

if __name__ == "__main__":
    token = os.getenv('DISCORD_TOKEN')
    if token:
        print("🔧 Запуск бота...")
        bot.run(token)
    else:
        print("❌ Ошибка: Токен не найден!")
        print("📝 Создайте файл .env с содержимым:")
        print("DISCORD_TOKEN=your_bot_token_here")
        print("🔗 Получите токен на https://discord.com/developers/applications")