# karakeep-webarchive-bot
A discord bot to use web archive as a middle-man between web pages and karakeep.

This is not meant to be used in production. I am not a developer. This code is buggy but it does what it needs to do. It is intended as a proof of concept to demonstrate that karakeep could benefit from allowing users the choice to pass urls to archive.org before (or after) karakeep tries to directly archive them itself. This should greatly increase the success rate of karakeep scraping the content, since archive.org is much better at doing so than most.

All this does is the following:
 - user shares a link to a designated discord channel
 - bot detects url
 - sends url to web.archive.org
 - waits for the archived version of the url
 - submits archive.org url to karakeep
 - deletes user's original message to keep channel clean

This allows easily accomplishing this workflow via desktop or mobile.

Setup requires you to create a discord bot with the following permissions: view channels, send messages, manage messages, read message history

Instructions on how to setup a discord bot not provided since this is not meant to be used in production.
