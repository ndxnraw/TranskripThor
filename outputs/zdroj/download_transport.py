"""Supervised local Hub worker: bounded waiting, resumable cache, no raw errors."""
import logging
import multiprocessing
import os
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path


@dataclass(frozen=True)
class DownloadLimits:
    idle: float = 90
    verification_idle: float = 180
    phase_max: float = 21600
    attempts: int = 3
    backoff: float = 2


def diagnostic_logger(cache):
    logger = logging.Logger('model_download')
    if not logger.handlers:
        Path(cache).mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(Path(cache)/'model-download.log', maxBytes=1_000_000, backupCount=2, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def status_text(event, silent=0):
    labels = {'connect':'Pripájam sa', 'lock':'Čakám na zámok cache', 'transfer':'Sťahujem',
              'verify':'Overujem obsah', 'finalize':'Dokončujem súbor', 'ready':'Model je pripravený'}
    text = labels.get(event['phase'], 'Pripravujem model') + ': ' + event.get('file','model')
    current, total = event.get('bytes',0), event.get('total')
    if total:
        text += f' • {current/1024**2:.1f}/{total/1024**2:.1f} MB'
    if event.get('count'):
        text += f' • súbor {event["count"]}'
    if silent >= 5:
        text += f' • bez nového postupu {int(silent)} s (časový limit je aktívny)'
    return text


def supervise(cache, model, emit, stop, limits=DownloadLimits(), worker=None):
    from download_worker import run_download
    context = multiprocessing.get_context('spawn')
    logger = diagnostic_logger(cache)
    logger.info('start model=%s transport=HTTP hub=0.36.2 xet=disabled', model)
    emit('download_state', True)
    try:
        for attempt in range(limits.attempts):
            if stop.is_set():
                raise InterruptedError('Sťahovanie zastavené. Rozpracované súbory zostali v cache; zvoľte Stiahnuť znova.')
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(target=worker or run_download, args=(str(cache),model,sender), daemon=True)
            event = dict(phase='connect',file=model)
            started = changed = last_ui = time.monotonic()
            signature = None
            failure = None
            complete = False
            try:
                process.start()
                sender.close()
                while True:
                    if stop.is_set():
                        raise InterruptedError('Sťahovanie zastavené. Rozpracované súbory zostali v cache; zvoľte Stiahnuť znova.')
                    try:
                        if receiver.poll(.1):
                            message = receiver.recv()
                            if message['kind'] == 'complete':
                                complete = True
                                break
                            if message['kind'] == 'error':
                                failure = (message['message'],message['retry'])
                                logger.warning('failure attempt=%s code=%s',attempt+1,message['code'])
                                break
                            event = message
                            new_signature = (event['phase'],event.get('file'),event.get('bytes'))
                            now = time.monotonic()
                            if new_signature != signature:
                                if signature is None or new_signature[:2] != signature[:2]:
                                    started = now
                                    logger.info('phase=%s file=%s attempt=%s',event['phase'],event.get('file'),attempt+1)
                                signature, changed = new_signature, now
                    except EOFError:
                        failure = ('Proces sťahovania sa neočakávane ukončil. Skúste znova; skontrolujte voľnú pamäť a ochranu počítača.',True)
                        break
                    now = time.monotonic()
                    timeout = limits.verification_idle if event['phase'] in ('verify','finalize') else limits.idle
                    if now-changed > timeout or now-started > limits.phase_max:
                        failure = (f'Časový limit: {status_text(event)}. Skontrolujte spojenie, voľné miesto alebo inú spustenú kópiu aplikácie a skúste znova.',True)
                        logger.warning('timeout phase=%s file=%s idle_seconds=%.1f',event['phase'],event.get('file'),now-changed)
                        break
                    if now-last_ui >= .5:
                        emit('status',status_text(event,now-changed))
                        last_ui = now
                    if not process.is_alive() and not receiver.poll():
                        failure = ('Proces sťahovania sa neočakávane ukončil. Skúste znova.',True)
                        break
            finally:
                if process.pid:
                    process.join(.5 if complete else 0)
                    if process.is_alive():
                        process.terminate()
                        process.join(2)
                    if process.is_alive():
                        process.kill()
                        process.join(2)
                    process.close()
                sender.close()
                receiver.close()
            if complete:
                logger.info('complete model=%s',model)
                emit('status','Model je overený a pripravený lokálne.')
                return
            message, retry = failure
            if not retry or attempt+1 == limits.attempts:
                raise RuntimeError(message)
            delay = limits.backoff * 2**attempt
            emit('status',f'{message}\nObnovenie pokusu {attempt+2}/{limits.attempts} o {delay:g} s; hotové súbory sa zachovajú.')
            if stop.wait(delay):
                raise InterruptedError('Sťahovanie zastavené; cache zostáva zachovaná.')
    finally:
        logger.info('download session ended')
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
        emit('download_state', False)
