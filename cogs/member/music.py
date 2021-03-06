# python3.6
# -*- coding: utf-8 -*-

import discord
from discord.ext import commands

import asyncio
import itertools, datetime
import sys
import traceback
from async_timeout import timeout
from functools import partial
from youtube_dl import YoutubeDL
from discord.ext.commands.cooldowns import BucketType

"""
discord.ext.commands music.py "cog"
    (https://github.com/F4stZ4p/DJ5n4k3/blob/master/modules/music.py)

Edited by AkiraSumato-01 for Rewrite-Discord-Bot-Naomi
    (https://github.com/AkiraSumato-01/Rewrite-Discord-Bot-Naomi)
"""

ytdlopts = {
    'format': 'bestaudio/best',
    'outtmpl': 'downloads/%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpegopts = {
    'before_options': '-nostdin -preset ultrafast',
    'options': '-vn -threads 1'
}

ytdl = YoutubeDL(ytdlopts)

if not discord.opus.is_loaded():
    discord.opus.load_opus('libopus.so')


class VoiceConnectionError(commands.CommandError):
    """Custom Exception class for connection errors."""


class InvalidVoiceChannel(VoiceConnectionError):
    """Exception for cases of invalid Voice Channels."""


class YTDLSource(discord.PCMVolumeTransformer):

    def __init__(self, source, *, data, requester):
        super().__init__(source)
        self.requester = requester

        self.title = data.get('title')

        if self.title is None:
            self.title = "No title available"

        self.web_url = data.get('webpage_url')
        self.thumbnail = data.get('thumbnail')

        if self.thumbnail is None:
            self.thumbnail = "http://ppc.tools/wp-content/themes/ppctools/img/no-thumbnail.jpg"

        self.duration = data.get('duration')

        if self.duration is None:
            self.duration = 0

        self.uploader = data.get('uploader')

        if self.uploader is None:
            self.uploader = "Неизвестно"
        
        # YTDL info dicts (data) have other useful information you might want
        # https://github.com/rg3/youtube-dl/blob/master/README.md

    def __getitem__(self, item: str):
        """Allows us to access attributes similar to a dict.

        This is only useful when you are NOT downloading.
        """
        return self.__getattribute__(item)

    @classmethod
    async def create_source(cls, ctx, search: str, *, loop, download=False):
        loop = loop or asyncio.get_event_loop()

        to_run = partial(ytdl.extract_info, url=search, download=download)
        data = await loop.run_in_executor(None, to_run)

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        await ctx.send(f':notes: Добавлено в очередь: **{data["title"]}**')

        if download:
            source = ytdl.prepare_filename(data)
        else:
            return {'webpage_url': data['webpage_url'], 'requester': ctx.author, 'title': data['title']}

        return cls(discord.FFmpegPCMAudio(source), data=data, requester=ctx.author)

    @classmethod
    async def regather_stream(cls, data, *, loop):
        """Used for preparing a stream, instead of downloading.

        Since Youtube Streaming links expire."""
        loop = loop or asyncio.get_event_loop()
        requester = data['requester']

        to_run = partial(ytdl.extract_info, url=data['webpage_url'], download=False)
        data = await loop.run_in_executor(None, to_run)

        return cls(discord.FFmpegPCMAudio(data['url']), data=data, requester=requester)


class MusicPlayer:
    """A class which is assigned to each guild using the bot for Music.

    This class implements a queue and loop, which allows for different guilds to listen to different playlists
    simultaneously.

    When the bot disconnects from the Voice it's instance will be destroyed.
    """

    __slots__ = ('bot', '_guild', '_ctxs', '_channel', '_cog', 'queue', 'next', 'current', 'np', 'volume', 'buttons', 'music', 'music_controller', 'restmode')

    def __init__(self, ctx):

        self.buttons = {'⏯': 'rp',
                        '⏭': 'skip',
                        '➕': 'vol_up',
                        '➖': 'vol_down',
                        '🖼': 'thumbnail',
                        '⏹': 'stop',
                        'ℹ': 'queue',
                        '❔': 'tutorial'}

        self.bot = ctx.bot
        self._guild = ctx.guild
        self._ctxs = ctx
        self._channel = ctx.channel
        self._cog = ctx.cog

        self.queue = asyncio.Queue()
        self.next = asyncio.Event()

        self.np = None
        self.volume = .5
        self.current = None
        self.music_controller = None

        ctx.bot.loop.create_task(self.player_loop())

    async def buttons_controller(self, guild, current, source, channel, context):
        vc = guild.voice_client
        vctwo = context.voice_client

        for react in self.buttons:
            await current.add_reaction(str(react))

        def check(r, u):
            if not current:
                return False
            elif str(r) not in self.buttons.keys():
                return False
            elif u.id == self.bot.user.id or r.message.id != current.id:
                return False
            elif u not in vc.channel.members:
                return False
            elif u.bot:
                return False
            return True

        while current:
            if vc is None:
                return False

            react, user = await self.bot.wait_for('reaction_add', check=check)
            control = self.buttons.get(str(react))

            if control == 'rp':
                if vc.is_paused():
                    vc.resume()
                else:
                    vc.pause()

            if control == 'skip':
                vc.stop()

            if control == 'stop':
                await context.invoke(self.bot.get_command("stop"))
                await channel.send('**:notes: Проигрывание завершено.**', delete_after=5)

            if control == 'vol_up':
                player = self._cog.get_player(context)
                vctwo.source.volume += 2.5
                        
            if control == 'vol_down':
                player = self._cog.get_player(context)
                vctwo.source.volume -= 2.5

            if control == 'thumbnail':
                await channel.send(embed=discord.Embed(color=0x17FD6E).set_image(url=source.thumbnail).set_footer(text=f"Запросил: {source.requester} | Видео: {source.title}", icon_url=source.requester.avatar_url), delete_after=10)

            if control == 'tutorial':
                await channel.send(embed=discord.Embed(color=0x17FD6E).add_field(name="Как использовать контроллер?", value="⏯ - Пауза\n⏭ - Пропустить\n➕ - Увеличить громкость\n➖ - Понизить громкость\n🖼 - Получить превью\n⏹ - Остановить проигрывание\nℹ - Очередь\n❔ - Показать справку по контроллеру"), delete_after=10)
            
            if control == 'queue':
                await self._cog.queue_info(context)

            try:
                await current.remove_reaction(react, user)
            except discord.HTTPException:
                pass

    async def player_loop(self):
        """Our main player loop."""
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            self.next.clear()

            try:
                async with timeout(3500):
                    source = await self.queue.get()
            except asyncio.TimeoutError:
                return self.destroy(self._guild)

            if not isinstance(source, YTDLSource):
                # Source was probably a stream (not downloaded)
                # So we should regather to prevent stream expiration
                try:
                    source = await YTDLSource.regather_stream(source, loop=self.bot.loop)
                except Exception as e:
                    await self._channel.send(f':notes: Возникла ошибка.\n'
                                             f'```css\n[{e}]\n```')
                    continue

            source.volume = self.volume
            self.current = source
            try:
                self._guild.voice_client.play(source, after=lambda _: self.bot.loop.call_soon_threadsafe(self.next.set))
            except Exception:
                continue
            embednps = discord.Embed(color=0x17FD6E)
            embednps.add_field(name="Проигрывается:", value=f"```fix\n{source.title}```", inline=False)
            embednps.add_field(name="Запросил:", value=f"**{source.requester}**", inline=True)
            embednps.add_field(name="URL-ссылка:", value=f"**[URL]({source.web_url})**", inline=True)
            embednps.add_field(name="Загрузил:", value=f"**{source.uploader}**", inline=True)
            embednps.add_field(name="Длительность:", value=f"**{datetime.timedelta(seconds=source.duration)}**", inline=True)
            embednps.set_thumbnail(url=source.thumbnail)
            self.np = await self._channel.send(embed=embednps)

            self.music_controller = self.bot.loop.create_task(self.buttons_controller(self._guild, self.np, source, self._channel, self._ctxs))
            await self.next.wait()

            # Make sure the FFmpeg process is cleaned up.
            source.cleanup()
            self.current = None

            try:
                # We are no longer playing this song...
                await self.np.delete()
                self.music_controller.cancel()
            except Exception:
                pass

    def destroy(self, guild):
        """Disconnect and cleanup the player."""
        return self.bot.loop.create_task(self._cog.cleanup(guild))

class Music:
    """Команды проигрывателя музыки."""

    __slots__ = ('bot', 'players', 'musictwo', 'music_controller')

    def __init__(self, bot):
        self.bot = bot
        self.players = {}

    async def cleanup(self, guild):
        try:
            await guild.voice_client.disconnect()
        except AttributeError:
            pass

        try:
            del self.players[guild.id]
        except KeyError:
            pass

    async def __local_check(self, ctx):
        """A local check which applies to all commands in this cog."""
        if not ctx.guild:
            raise commands.NoPrivateMessage
        return True

    async def cleanup(self, guild):
        try:
            await guild.voice_client.disconnect()
        except AttributeError:
            pass

        try:
            del self.players[guild.id]
        except KeyError:
            pass

    async def __error(self, ctx, error):
        """A local error handler for all errors arising from commands in this cog."""
        if isinstance(error, commands.NoPrivateMessage):
            try:
                return await ctx.send(':notes: Команда не может быть использована в ЛС.')
            except discord.HTTPException:
                pass
        elif isinstance(error, InvalidVoiceChannel):
            await ctx.send(":notes: Вы не подключены к голосовому каналу.")

        print('Ignoring exception in command {}:'.format(ctx.command), file=sys.stderr)
        traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)

    def get_player(self, ctx):
        """Retrieve the guild player, or generate one."""
        try:
            player = self.players[ctx.guild.id]
        except KeyError:
            player = MusicPlayer(ctx)
            self.players[ctx.guild.id] = player

        return player

    @commands.command(name='stop', aliases=['leave', 'l', 'disconnect'])
    async def disconnect_(self, ctx):
        """Остановить проигрыватель и отключить меня от голосового канала.
        """

        try:
            channel = ctx.author.voice.channel
        except AttributeError:
            await ctx.send(":notes: Вы не подключены к голосовому каналу.", delete_after=20)

        if not ctx.guild.voice_client:
            return await ctx.send(':notes: Я не нахожусь в голосовом канале.', delete_after=20)

        await ctx.guild.voice_client.disconnect()
        await ctx.send(':notes: Успешно.', delete_after=20)



    @commands.command(name='reconnect', aliases=['rc'])
    async def reconnect_(self, ctx):
        """Переподключить меня к голосовому каналу.
        """
        try:
            channel = ctx.author.voice.channel

        except AttributeError:
            return await ctx.send(":notes: Вы не подключены к голосовому каналу.", delete_after=20)

        if ctx.guild.voice_client:
            await ctx.guild.voice_client.disconnect()

        await channel.connect()



    @commands.command(name='connect', aliases=['join', 'j'])
    async def connect_(self, ctx, *, channel: discord.VoiceChannel=None):
        """Подключить меня к голосовому каналу.

        Аргументы:
        `:channel` - название голосового канала
        __                                            __
        Например:
        ```
        n!connect музыка
        n!join music
        ```
        """

        if not channel:
            try:
                channel = ctx.author.voice.channel
            except AttributeError:
                await ctx.send(":notes: Вы не подключены к голосовому каналу.", delete_after=20)

        vc = ctx.voice_client
        
        if vc:
            if vc.channel.id == channel.id:
                return
            try:
                await vc.move_to(channel)
            except asyncio.TimeoutError:
                return await ctx.send(f':notes: :x: Переход в <{channel}> не удался...\nПревышено время ожидания. Попробуйте еще раз.')
                #raise VoiceConnectionError(f'Переход в <{channel}> закончилось неудачей;\n Timeout.')
        else:
            try:
                await channel.connect()
            except asyncio.TimeoutError:
                return await ctx.send(f':notes: :x: Подключение к <{channel}> не удалось...\nПревышено время ожидания. Попробуйте еще раз.')
                # raise VoiceConnectionError(f'Подключение к <{channel}> закончилось неудачей;\n Timeout.')

        await ctx.send(f":notes: Голосовой канал: **{channel}**", delete_after=20)
        


    @commands.command(name='play', aliases=['sing', 'p'])
    async def play_(self, ctx, *, search: str):
        """Проигрывание музыки (видео YouTube).

        Аргументы:
        `:search` - название песни или ссылка на видео YouTube
        __                                            __
        Например:
        ```
        n!play Nightcore - Mayday
        ```
        """
        
        await ctx.trigger_typing()

        vc = ctx.voice_client

        if not vc:
            await ctx.invoke(self.connect_)

        elif ctx.author not in ctx.guild.voice_client.channel.members:
            return await ctx.send(":notes: Подключитесь к голосовому каналу.", delete_after=20)

        player = self.get_player(ctx)

        # If download is False, source will be a dict which will be used later to regather the stream.
        # If download is True, source will be a discord.FFmpegPCMAudio with a VolumeTransformer.
        source = await YTDLSource.create_source(ctx, search, loop=self.bot.loop, download=False)
        await player.queue.put(source)



    @commands.command(name='playing', aliases=['np', 'current', 'currentsong', 'now_playing'])
    async def now_playing_(self, ctx):
        """Отобразить информацию о проигрываемом треке.
        """

        vc = ctx.voice_client

        if not vc or not vc.is_connected():
            return await ctx.send(":notes: Я не нахожусь в голосовом канале. Присоединитесь к любому из них и выполните команду..", delete_after=20)

        elif ctx.author not in ctx.guild.voice_client.channel.members:
            return await ctx.send(":notes: Подключитесь к голосовому каналу.", delete_after=20)

        player = self.get_player(ctx)
        if not player.current:
            return await ctx.send(":notes: Проигрывание неактивно в данный момент.", delete_after=20)

        try:
            # Remove our previous now_playing message.
            await player.np.delete()
        except discord.HTTPException:
            pass

        embednp = discord.Embed(color=0x17FD6E)
        embednp.add_field(name="Проигрывается:", value=f"```fix\n{vc.source.title}```", inline=False)
        embednp.add_field(name="Запросил:", value=f"**{vc.source.requester}**", inline=True)
        embednp.add_field(name="URL-ссылка:", value=f"**[URL]({vc.source.web_url})**", inline=True)
        embednp.add_field(name="Загрузил:", value=f"**{vc.source.uploader}**", inline=True)
        embednp.add_field(name="Длительность:", value=f"**{datetime.timedelta(seconds=vc.source.duration)}**", inline=True)
        embednp.set_thumbnail(url=f"{vc.source.thumbnail}")
        player.np = await ctx.send(embed=embednp)
        self.music_controller = self.bot.loop.create_task(MusicPlayer(ctx).buttons_controller(ctx.guild, player.np, vc.source, ctx.channel, ctx))

    async def queue_info(self, ctx):
        player = self.get_player(ctx)
        if player.queue.empty():
            return await ctx.send('**:notes: Нет песен в очереди.**')

        upcoming = list(itertools.islice(player.queue._queue, 0, 5))

        fmt = '\n'.join(f'**`{_["title"]}`**' for _ in upcoming)
        embed = discord.Embed(title=f'Очередь - Следующий {len(upcoming)}', description=fmt, color=0x17FD6E)
        await ctx.send(embed=embed)

def setup(bot):
    bot.add_cog(Music(bot))
    print('[music.py] Музыкальный модуль загружен.')
