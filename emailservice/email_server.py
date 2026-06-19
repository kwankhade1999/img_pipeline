#!/usr/bin/python
#
# Copyright 2018 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from concurrent import futures
import os
import time
import smtplib
import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import grpc
from jinja2 import Environment, FileSystemLoader, select_autoescape, TemplateError
from google.auth.exceptions import DefaultCredentialsError

import demo_pb2
import demo_pb2_grpc
from grpc_health.v1 import health_pb2
from grpc_health.v1 import health_pb2_grpc

from opentelemetry import trace
from opentelemetry.instrumentation.grpc import GrpcInstrumentorServer
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from logger import getJSONLogger
logger = getJSONLogger('emailservice-server')

# Loads confirmation email template from file
env = Environment(
    loader=FileSystemLoader('templates'),
    autoescape=select_autoescape(['html', 'xml'])
)
template = env.get_template('confirmation.html')


class BaseEmailService(demo_pb2_grpc.EmailServiceServicer):
  def Check(self, request, context):
    return health_pb2.HealthCheckResponse(
      status=health_pb2.HealthCheckResponse.SERVING)

  def Watch(self, request, context):
    return health_pb2.HealthCheckResponse(
      status=health_pb2.HealthCheckResponse.UNIMPLEMENTED)


class GmailEmailService(BaseEmailService):
  """Sends real order confirmation emails via Gmail SMTP.

  Requires env vars:
    GMAIL_ADDRESS      - the Gmail address used as sender (e.g. you@gmail.com)
    GMAIL_APP_PASSWORD - a Gmail App Password (not your regular password)
  """

  def __init__(self):
    self.gmail_address = os.environ['GMAIL_ADDRESS']
    self.gmail_app_password = os.environ['GMAIL_APP_PASSWORD']
    super().__init__()

  def _send_email(self, to_address, html_content):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = 'Your Order Confirmation'
    msg['From'] = self.gmail_address
    msg['To'] = to_address
    msg.attach(MIMEText(html_content, 'html'))

    with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
      smtp.ehlo()
      smtp.starttls()
      smtp.login(self.gmail_address, self.gmail_app_password)
      smtp.sendmail(self.gmail_address, to_address, msg.as_string())

  def SendOrderConfirmation(self, request, context):
    email = request.email
    order = request.order

    try:
      confirmation = template.render(order=order)
    except TemplateError as err:
      context.set_details("An error occurred when preparing the confirmation mail.")
      logger.error(str(err))
      context.set_code(grpc.StatusCode.INTERNAL)
      return demo_pb2.Empty()

    try:
      self._send_email(email, confirmation)
      logger.info("Order confirmation email sent to {}".format(email))
    except Exception as err:
      context.set_details("An error occurred when sending the email.")
      logger.error("Failed to send email to {}: {}".format(email, str(err)))
      context.set_code(grpc.StatusCode.INTERNAL)
      return demo_pb2.Empty()

    return demo_pb2.Empty()


class DummyEmailService(BaseEmailService):
  def SendOrderConfirmation(self, request, context):
    logger.info('A request to send order confirmation email to {} has been received.'.format(request.email))
    return demo_pb2.Empty()


def start(dummy_mode):
  server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
  if dummy_mode:
    service = DummyEmailService()
    logger.info("Starting in DUMMY mode — emails will not be sent.")
  else:
    service = GmailEmailService()
    logger.info("Starting in GMAIL mode — emails will be sent via Gmail SMTP.")

  demo_pb2_grpc.add_EmailServiceServicer_to_server(service, server)
  health_pb2_grpc.add_HealthServicer_to_server(service, server)

  port = os.environ.get('PORT', "8080")
  logger.info("listening on port: " + port)
  server.add_insecure_port('[::]:' + port)
  server.start()
  try:
    while True:
      time.sleep(3600)
  except KeyboardInterrupt:
    server.stop(0)


if __name__ == '__main__':
  # Use Gmail SMTP when credentials are provided; fall back to dummy mode
  dummy_mode = not (os.environ.get('GMAIL_ADDRESS') and os.environ.get('GMAIL_APP_PASSWORD'))
  if dummy_mode:
    logger.info('Starting email service in DUMMY mode (set GMAIL_ADDRESS and GMAIL_APP_PASSWORD to enable real sending).')
  else:
    logger.info('Starting email service in GMAIL mode.')

  # Tracing
  try:
    if os.environ["ENABLE_TRACING"] == "1":
      otel_endpoint = os.getenv("COLLECTOR_SERVICE_ADDR", "localhost:4317")
      trace.set_tracer_provider(TracerProvider())
      trace.get_tracer_provider().add_span_processor(
        BatchSpanProcessor(
          OTLPSpanExporter(
            endpoint=otel_endpoint,
            insecure=True
          )
        )
      )
    grpc_server_instrumentor = GrpcInstrumentorServer()
    grpc_server_instrumentor.instrument()

  except (KeyError, DefaultCredentialsError):
    logger.info("Tracing disabled.")
  except Exception as e:
    logger.warning(f"Exception on Cloud Trace setup: {traceback.format_exc()}, tracing disabled.")

  start(dummy_mode=dummy_mode)
