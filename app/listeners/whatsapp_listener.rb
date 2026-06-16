class WhatsappListener < BaseListener
  include Events::Types

  def conversation_typing_on(event)
    conversation = event.data[:conversation]
    return unless whatsapp_channel?(conversation)

    channel = conversation.inbox.channel
    last_message = conversation.messages.incoming.last
    return unless last_message

    channel.toggle_typing_status(CONVERSATION_TYPING_ON, last_message: last_message)
  end

  def message_created(event)
    message = extract_message_and_account(event)[0]
    return unless message.outgoing?
    return unless whatsapp_channel?(message.conversation)

    incoming_messages = message.conversation.messages.incoming
    return if incoming_messages.empty?

    message.conversation.inbox.channel.read_messages(incoming_messages)
  rescue StandardError => e
    Rails.logger.error("WhatsappListener: Failed to mark messages as read: #{e.message}")
  end

  private

  def whatsapp_channel?(conversation)
    conversation.inbox.channel_type == 'Channel::Whatsapp'
  end
end
