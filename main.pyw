import threading
import datetime
import configparser

import wx
from wx.lib.newevent import NewEvent
import wx.lib.masked as masked
import stripe
stripe.http_client.urlfetch = None


CustomersFetchedEvent, EVT_CUSTOMERS_FETCHED = NewEvent()
CustomerDetailEvent, EVT_CUSTOMER_DETAIL = NewEvent()
AddCustomerEvent, EVT_ADD_CUSTOMER = NewEvent()
AddCardEvent, EVT_ADD_CARD = NewEvent()
CreateChargeEvent, EVT_CREATE_CHARGE = NewEvent()
CreateRefundEvent, EVT_CREATE_REFUND = NewEvent()

GREEN = [209, 255, 209]
YELLOW = [255, 255, 209]
RED = [255, 209, 209]
BLUE = [209, 209, 255]
PURPLE = [255, 209, 255]


def get_paged_stripe_data(stripe_func, **kwargs):
    response = stripe_func(**kwargs)
    results = [item for item in response.data]
    while response.has_more:
        lastid = response.data[-1].id
        response = stripe_func(starting_after=lastid, **kwargs)
        results += [item for item in response.data]
    return results


def fetch_customers(win):
    customers = get_paged_stripe_data(stripe.Customer.list, limit=100)
    wx.PostEvent(win, CustomersFetchedEvent(customers=customers))


def fetch_detail(win, customer):
    cards = get_paged_stripe_data(customer.sources.list, limit=100)
    charges = get_paged_stripe_data(
        stripe.Charge.list, limit=100, customer=customer.id)
    wx.PostEvent(win, CustomerDetailEvent(
        customer=customer, cards=cards, charges=charges))


def add_customer(win, code, description):
    customer = stripe.Customer.create(metadata={'Code': code},
                                      description=description)
    wx.PostEvent(win, AddCustomerEvent(customer=customer))


def add_card(win, customer, number, exp_month, exp_year, cvc=None):
    card = {
        'object': 'card',
        'number': number,
        'exp_month': exp_month,
        'exp_year': exp_year}
    if cvc:
        card['cvc'] = cvc
    try:
        card = customer.sources.create(source=card)
    except stripe.error.CardError as e:
        wx.PostEvent(win, AddCardEvent(error=e, card=None))
    else:
        wx.PostEvent(win, AddCardEvent(error=None, card=card))


def create_charge(win, customer, card, amount, description):
    try:
        charge = stripe.Charge.create(
            currency='usd', customer=customer.id, source=card.id,
            amount=amount, description=description)
    except stripe.error.CardError as e:
        charge = stripe.Charge.retrieve(e.json_body['error']['charge'])
        wx.PostEvent(win, CreateChargeEvent(error=e, charge=charge))
    else:
        wx.PostEvent(win, CreateChargeEvent(error=None, charge=charge))


def create_refund(win, charge, amount):
    try:
        refund = stripe.Refund.create(
            charge=charge.id, amount=amount)
    except (stripe.error.CardError, stripe.error.InvalidRequestError) as e:
        wx.PostEvent(win, CreateRefundEvent(error=e, refund=None))
    else:
        wx.PostEvent(win, CreateRefundEvent(error=None, refund=refund,
                                            charge=charge))


class MainFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(MainFrame, self).__init__(*args, **kwargs)

        self.customer_list = CustomerList(self)
        self.customer_detail = CustomerDetail(self)
        self.status = self.CreateStatusBar(1)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(self.customer_list, 0, wx.EXPAND)
        hbox.Add(self.customer_detail, 1, wx.EXPAND)
        self.SetSizer(hbox)

        self.Bind(EVT_CUSTOMERS_FETCHED, self.on_customers_fetched)
        self.Bind(EVT_CUSTOMER_DETAIL, self.on_detail_fetched)

        self.SetSize(650, 650)
        self.load_config()
        self.load_customers()

    def load_config(self):
        self.config = configparser.SafeConfigParser()
        self.config.read('settings.cfg')
        stripe.api_key = self.config.get('Stripe', 'api_key')
        try:
            self.config.add_section('Stripe')
        except configparser.DuplicateSectionError:
            pass

    def load_customers(self):
        wx.BeginBusyCursor()
        self.status.SetStatusText('Loading customers...')
        self.busywin = wx.BusyInfo('Loading customer data...', self)
        self.customer_list.Disable()
        self.customer_detail.Disable()
        self.customer_detail.set_detail(None, None, None)
        t = threading.Thread(target=fetch_customers, args=(self,))
        t.setDaemon(True)
        t.start()

    def display_customer_detail(self, customer):
        self.customer_list.Disable()
        self.customer_detail.Disable()
        t = threading.Thread(target=fetch_detail, args=(self, customer))
        t.setDaemon(True)
        t.start()
        return

    def on_customers_fetched(self, e):
        self.customer_list.set_customers(e.customers)
        self.customer_list.Enable()
        wx.EndBusyCursor()
        del self.busywin
        self.status.SetStatusText('{} customers'.format(len(e.customers)))
        self.Layout()

    def on_detail_fetched(self, e):
        self.customer_detail.set_detail(e.customer, e.cards, e.charges)
        self.customer_list.Enable()
        self.customer_detail.Enable()
        self.Layout()


class CustomerList(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(CustomerList, self).__init__(*args, **kwargs)

        find = wx.StaticText(self, label='Find')
        clearfind = wx.Button(self, label='x', style=wx.BU_EXACTFIT)
        self.findbox = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.findbox.SetMinSize((85, -1))
        label = wx.StaticText(self, label='Customers')
        self.listbox = wx.ListBox(self, style=wx.LB_SINGLE | wx.LB_SORT)
        add_button = wx.Button(self, label='Add Customer')
        reload_button = wx.Button(self, label='Reload')

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(self.findbox, 1, wx.EXPAND)
        hbox.Add(clearfind)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(find, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        vbox.Add(hbox, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        vbox.Add(label, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        vbox.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        vbox.Add(add_button, 0, wx.EXPAND | wx.TOP | wx.LEFT | wx.RIGHT, 10)
        vbox.Add(reload_button, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(vbox)

        self.listbox.Bind(wx.EVT_LISTBOX, self.on_selection)
        self.findbox.Bind(wx.EVT_TEXT, self.on_filter)
        self.findbox.Bind(wx.EVT_TEXT_ENTER, self.on_filter_enter)
        add_button.Bind(wx.EVT_BUTTON, self.on_add)
        reload_button.Bind(wx.EVT_BUTTON, self.on_refresh)
        clearfind.Bind(wx.EVT_BUTTON, self.on_clear_find)

    def set_customers(self, customers):
        self.customers = customers
        self.listbox.Set([c.metadata['Code'] for c in self.customers])

    def add_customer(self, customer):
        self.customers.append(customer)
        self.listbox.Set([c.metadata['Code'] for c in self.customers])
        self.listbox.SetStringSelection(customer.metadata['Code'])
        self.on_selection(None)

    def on_add(self, e):
        dialog = AddCustomerDialog(self, title='Add Customer')
        dialog.ShowModal()
        dialog.Destroy()

    def on_refresh(self, e):
        self.Parent.load_customers()

    def on_clear_find(self, e):
        self.findbox.SetValue('')

    def on_selection(self, e):
        selection = self.listbox.GetStringSelection()
        for customer in self.customers:
            if selection == customer.metadata['Code']:
                self.Parent.display_customer_detail(customer)
                return

    def on_filter(self, e):
        txt = self.findbox.GetValue().upper()
        if txt:
            self.listbox.Set(
                [c.metadata['Code'] for c in self.customers
                    if txt in c.metadata['Code']])
        else:
            self.listbox.Set([c.metadata['Code'] for c in self.customers])

    def on_filter_enter(self, e):
        idx = self.listbox.FindString(self.findbox.GetValue())
        if idx is wx.NOT_FOUND:
            code = self.findbox.GetValue().upper()
            dialog = AddCustomerDialog(self, title='Add Customer', code=code)
            dialog.ShowModal()
            dialog.Destroy()
        else:
            self.listbox.SetSelection(idx)
            self.on_selection(None)


class CustomerDetail(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(CustomerDetail, self).__init__(*args, **kwargs)

        self.code = wx.StaticText(self)
        self.name = wx.StaticText(self)
        cards = wx.StaticText(self, label='Cards')
        add_card = wx.Button(self, label='Add Card')
        self.cards_list = CardList(self)
        charges = wx.StaticText(self, label='Charges')
        create_refund = wx.Button(self, label='Issue Refund')
        create_charge = wx.Button(self, label='Create Charge')
        self.charge_list = ChargeList(self)

        font = self.code.GetFont()
        font.MakeBold().SetPointSize(18)
        self.code.SetFont(font)

        card_header = wx.BoxSizer(wx.HORIZONTAL)
        card_header.Add(cards, flag=wx.ALIGN_BOTTOM)
        card_header.AddStretchSpacer(1)
        card_header.Add(add_card)

        charges_header = wx.BoxSizer(wx.HORIZONTAL)
        charges_header.Add(charges, flag=wx.ALIGN_BOTTOM)
        charges_header.AddStretchSpacer(1)
        charges_header.Add(create_refund)
        charges_header.Add(create_charge)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(self.code, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        vbox.Add(self.name, 0, wx.ALIGN_CENTER | wx.LEFT | wx.RIGHT, 10)
        vbox.Add(card_header, 0, wx.EXPAND | wx.TOP | wx.LEFT | wx.RIGHT, 10)
        vbox.Add(
            self.cards_list, 2, wx.EXPAND | wx.TOP | wx.LEFT | wx.RIGHT, 10)
        vbox.Add(
            charges_header, 0, wx.EXPAND | wx.TOP | wx.LEFT | wx.RIGHT, 10)
        vbox.Add(self.charge_list, 3, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(vbox)

        create_charge.Bind(wx.EVT_BUTTON, self.on_create_charge)
        add_card.Bind(wx.EVT_BUTTON, self.on_add_card)
        create_refund.Bind(wx.EVT_BUTTON, self.on_create_refund)
        self.Disable()

    def set_detail(self, customer, cards, charges):
        self.customer = customer
        if customer:
            self.code.SetLabel(customer.metadata['Code'].replace('&', '&&'))
            self.name.SetLabel(customer.description.replace('&', '&&'))
        else:
            self.code.SetLabel('')
            self.name.SetLabel('')
        self.cards_list.set_cards(cards)
        self.charge_list.set_charges(charges)

    def add_card(self, card):
        self.cards_list.add_card(card)

    def on_add_card(self, e):
        dialog = AddCardDialog(self, title='Add Credit Card')
        dialog.ShowModal()
        dialog.Destroy()

    def add_charge(self, charge):
        self.charge_list.add_charge(charge)

    def on_create_charge(self, e):
        if not self.cards_list.cards:
            wx.MessageBox(
                'Customer has no cards to charge.',
                'Error creating charge', wx.OK | wx.ICON_ERROR)
            return
        card = self.cards_list.GetFirstSelected()
        if card == -1:
            card = None
        dialog = CreateChargeDialog(
            self, title='Charge Credit Card', customer=self.customer,
            cards=self.cards_list.cards, card_index=card)
        dialog.ShowModal()
        dialog.Destroy()

    def add_refund(self, refund, charge):
        charges = self.charge_list.charges
        index = charges.index(charge)
        charges[index].amount_refunded += refund.amount
        if charges[index].amount_refunded == charge.amount:
            charges[index].refunded = True
        charges[index].refunds.data.insert(0, refund)
        self.charge_list.set_charges(charges)

    def on_create_refund(self, e):
        sel = self.charge_list.GetFirstSelected()
        if sel == -1:
            wx.MessageBox(
                'You must select a charge to refund.',
                'Error creating refund', wx.OK | wx.ICON_ERROR)
            return
        charge = self.charge_list.GetItemData(sel)
        if charge == -1:
            wx.MessageBox(
                'You can not refund a refund.',
                'Error creating refund', wx.OK | wx.ICON_ERROR)
            return
        charge = self.charge_list.charges[charge]
        if charge.status == 'failed':
            wx.MessageBox(
                'You can not refund a failed charge.',
                'Error creating refund', wx.OK | wx.ICON_ERROR)
            return
        if charge.refunded:
            wx.MessageBox(
                'Charge has already been refunded.',
                'Error creating refund', wx.OK | wx.ICON_ERROR)
            return
        dialog = CreateRefundDialog(
            self, title='Refund Credit Card', charge=charge)
        dialog.ShowModal()
        dialog.Destroy()


class CardList(wx.ListCtrl):
    def __init__(self, *args, **kwargs):
        super(CardList, self).__init__(style=wx.LC_SINGLE_SEL | wx.LC_REPORT,
                                       *args, **kwargs)
        self.InsertColumn(0, 'Card Info')
        self.InsertColumn(1, 'Expiration')
        self.cards = []
        self.imgs = wx.ImageList(32, 20)
        self.imgs.Add(wx.Bitmap('assets/visa.png'))
        self.imgs.Add(wx.Bitmap('assets/mc.png'))
        self.imgs.Add(wx.Bitmap('assets/disc.png'))
        self.imgs.Add(wx.Bitmap('assets/amex.png'))
        self.SetImageList(self.imgs, wx.IMAGE_LIST_SMALL)

    def _resize_cols(self):
        self.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        self.SetColumnWidth(1, wx.LIST_AUTOSIZE_USEHEADER)

    def _fill_row(self, card, index=None):
        if index is None:
            index = self.GetItemCount()
        cardstr = '{} ending in {}'.format(card.brand, card.last4)
        exp = '{}/{}'.format(card.exp_month, card.exp_year)
        cards = ['Visa', 'MasterCard', 'Discover', 'American Express']
        self.InsertItem(index, cardstr, cards.index(card.brand))
        self.SetItem(index, 1, exp)

    def set_cards(self, cards):
        self.DeleteAllItems()
        self.cards = None
        if cards:
            now = datetime.date.today()

            def expired(card):
                if card.exp_year < now.year:
                    return True
                if card.exp_year == now.year and card.exp_month < now.month:
                    return True
                else:
                    return False
            self.cards = [card for card in cards if not expired(card)]
            for card in self.cards:
                self._fill_row(card)
            self._resize_cols()

    def add_card(self, card):
        self.cards.insert(0, card)
        self._fill_row(card, 0)
        self._resize_cols()


class ChargeList(wx.ListCtrl):
    def __init__(self, *args, **kwargs):
        super(ChargeList, self).__init__(style=wx.LC_REPORT | wx.LC_SINGLE_SEL,
                                         *args, **kwargs)
        self.InsertColumn(0, 'Date')
        self.InsertColumn(1, 'Amount')
        self.InsertColumn(2, 'Card Info')
        self.InsertColumn(3, 'Expiration')
        self.InsertColumn(4, 'Status')
        self.charges = []

    def _resize_cols(self):
        self.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        self.SetColumnWidth(1, wx.LIST_AUTOSIZE_USEHEADER)
        self.SetColumnWidth(2, wx.LIST_AUTOSIZE_USEHEADER)
        self.SetColumnWidth(3, wx.LIST_AUTOSIZE_USEHEADER)
        self.SetColumnWidth(4, wx.LIST_AUTOSIZE_USEHEADER)

    def _fill_row(self, charge, index=None):
        if index is None:
            index = self.GetItemCount()
        date = datetime.date.fromtimestamp(charge.created).strftime('%x')
        amt = '${0:.02f}'.format(charge.amount / 100.0)
        card = '{} ending in {}'.format(
            charge.source.brand, charge.source.last4)
        exp = '{}/{}'.format(charge.source.exp_month, charge.source.exp_year)
        color = wx.Colour(*GREEN)
        if charge.refunded:
            status = 'Refunded'
        elif charge.amount_refunded:
            status = 'Partial Refund'
        elif charge.status == 'succeeded':
            status = 'Success'
        elif charge.status == 'pending':
            status = 'Pending'
            color = wx.Colour(*YELLOW)
        else:
            status = 'Failed'
            color = wx.Colour(*RED)
        self.InsertItem(index, date)
        self.SetItem(index, 1, amt)
        self.SetItem(index, 2, card)
        self.SetItem(index, 3, exp)
        self.SetItem(index, 4, status)
        self.SetItemBackgroundColour(index, color)
        self.SetItemData(index, self.charges.index(charge))
        for refund in charge.refunds:
            index = index + 1
            date = datetime.date.fromtimestamp(refund.created).strftime('%x')
            amt = '(${0:.02f})'.format(refund.amount / 100.0)
            if refund.status == 'succeeded':
                status = 'Refund'
                color = wx.Colour(*BLUE)
            else:
                status = 'Refund Failed'
                color = wx.Colour(*PURPLE)
            self.InsertItem(index, date)
            self.SetItem(index, 1, amt)
            self.SetItem(index, 2, '   see above')
            self.SetItem(index, 4, status)
            self.SetItemBackgroundColour(index, color)
            self.SetItemData(index, -1)

    def set_charges(self, charges):
        self.charges = charges or []
        self.DeleteAllItems()
        if charges:
            for charge in charges:
                self._fill_row(charge)
            self._resize_cols()

    def add_charge(self, charge):
        self.charges.insert(0, charge)
        self.set_charges(self.charges)
        self._resize_cols()


class AddCustomerDialog(wx.Dialog):
    def __init__(self, *args, **kwargs):
        passed = kwargs.pop('code', None)
        super(AddCustomerDialog, self).__init__(*args, **kwargs)

        code = wx.StaticText(self, label='Customer Code')
        self.code_entry = wx.TextCtrl(self)
        name = wx.StaticText(self, label='Customer Name')
        self.name_entry = wx.TextCtrl(self)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(code, 0, wx.ALL, 10)
        vbox.Add(self.code_entry, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        vbox.Add(name, 0, wx.TOP | wx.LEFT | wx.RIGHT, 10)
        vbox.Add(
            self.name_entry, 0, wx.EXPAND | wx.TOP | wx.LEFT | wx.RIGHT, 10)
        vbox.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL, 10)
        self.SetSizer(vbox)

        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.Bind(EVT_ADD_CUSTOMER, self.on_customer_added)
        if passed:
            self.code_entry.SetValue(passed)
            self.name_entry.SetFocus()
        else:
            self.code_entry.SetFocus()
        self.Fit()

    def on_ok(self, e):
        self.Disable()
        code = self.code_entry.GetValue()
        desc = self.name_entry.GetValue()
        if not (code and desc):
            wx.MessageBox(
                'Must supply customer code and customer name.',
                'Error adding customer', wx.OK | wx.ICON_ERROR)
            self.Enable()
            return
        elif code in (c.metadata['Code'] for c in self.Parent.customers):
            wx.MessageBox(
                'Customer already exists.',
                'Error adding customer', wx.OK | wx.ICON_ERROR)
            self.Enable()
            return
        t = threading.Thread(target=add_customer, args=(self, code, desc))
        t.setDaemon(True)
        t.start()

    def on_customer_added(self, e):
        self.Parent.add_customer(e.customer)
        self.Destroy()


class AddCardDialog(wx.Dialog):
    default_mask = '#### #### #### ####'
    amex_mask = '#### ###### #####'
    default_cvc = '###'
    amex_cvc = '####'

    def __init__(self, *args, **kwargs):
        super(AddCardDialog, self).__init__(*args, **kwargs)

        cc_num_label = wx.StaticText(self, label='Credit Card Number')
        self.cc_num = masked.TextCtrl(self, mask=self.default_mask)
        month_label = wx.StaticText(self, label='Month')
        self.month = wx.Choice(self, choices=[str(n) for n in range(1, 13)])
        year_label = wx.StaticText(self, label='Year')
        self.year = wx.Choice(self)
        cvc_label = wx.StaticText(self, label='CVC')
        self.cvc = masked.TextCtrl(self, mask=self.default_cvc, size=(45, -1))

        year = datetime.date.today().year
        years = [str(n) for n in range(year, year + 20)]
        self.year.Set(years)

        month_box = wx.BoxSizer(wx.VERTICAL)
        month_box.Add(month_label, 0, wx.BOTTOM, 10)
        month_box.Add(self.month)

        year_box = wx.BoxSizer(wx.VERTICAL)
        year_box.Add(year_label, 0, wx.BOTTOM, 10)
        year_box.Add(self.year)

        cvc_box = wx.BoxSizer(wx.VERTICAL)
        cvc_box.Add(cvc_label, 0, wx.BOTTOM, 10)
        cvc_box.Add(self.cvc)

        date_row = wx.BoxSizer(wx.HORIZONTAL)
        date_row.Add(month_box)
        date_row.Add(year_box, 0, wx.LEFT | wx.RIGHT, 10)
        date_row.Add(cvc_box)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(cc_num_label, 0, wx.ALL, 10)
        vbox.Add(self.cc_num, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        vbox.Add(date_row, 0, wx.ALL, 10)
        vbox.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL, 10)
        self.SetSizer(vbox)

        self.cc_num.Bind(wx.EVT_TEXT, self.on_card_changed)
        self.Bind(EVT_ADD_CARD, self.on_card_added)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.cc_num.SetFocus()
        self.Fit()

    def on_card_changed(self, e):
        value = self.cc_num.GetPlainValue()
        cvc = self.cvc.GetPlainValue()
        current_mask = self.cc_num.GetMask()
        if value.startswith('3'):
            if current_mask != self.amex_mask:
                self.cc_num.SetMask(self.amex_mask)
                self.cc_num.ChangeValue(value)
                self.cvc.SetMask(self.amex_cvc)
                self.cvc.ChangeValue(cvc)
        elif current_mask != self.default_mask:
            self.cc_num.SetMask(self.default_mask)
            self.cc_num.ChangeValue(value)
            self.cvc.SetMask(self.default_cvc)
            self.cvc.ChangeValue(cvc[:3])

    def on_ok(self, e):
        self.Disable()
        number = self.cc_num.GetPlainValue()
        month = self.month.GetStringSelection()
        year = self.year.GetStringSelection()
        cvc = self.cvc.GetPlainValue()
        if not (number and month and year):
            wx.MessageBox(
                'Must supply card number and expiration.',
                'Error adding card', wx.OK | wx.ICON_ERROR)
            self.Enable()
            return
        t = threading.Thread(
            target=add_card,
            args=(self, self.Parent.customer, number, month, year, cvc))
        t.setDaemon(True)
        t.start()

    def on_card_added(self, e):
        card = e.card
        if card:
            self.Parent.add_card(card)
            self.Destroy()
        else:
            error = e.error.json_body['error']
            wx.MessageBox(
                error['message'], 'Error adding card', wx.OK | wx.ICON_ERROR)
            self.Enable()


class CreateChargeDialog(wx.Dialog):
    def __init__(self, *args, **kwargs):
        self.customer = kwargs.pop('customer')
        self.cards = kwargs.pop('cards')
        self.card_index = kwargs.pop('card_index')
        if self.card_index is None:
            self.card_index = wx.NOT_FOUND
        super(CreateChargeDialog, self).__init__(*args, **kwargs)

        invoice_label = wx.StaticText(self, label='Invoice Number')
        self.invoice = wx.TextCtrl(self)
        amount_label = wx.StaticText(self, label='Amount')
        self.amount = masked.numctrl.NumCtrl(self)
        card_label = wx.StaticText(self, label='Payment Source')
        self.source = wx.Choice(self)

        self.amount.SetFractionWidth(2)
        self.amount.SetIntegerWidth(4)
        self.amount.SetAllowNegative(False)

        cs = '{} ending in {} expiring {}/{}'
        cardstrings = [cs.format(c.brand, c.last4, c.exp_month, c.exp_year)
                       for c in self.cards]
        self.source.Set(cardstrings)
        self.source.SetSelection(self.card_index)

        inv_box = wx.BoxSizer(wx.VERTICAL)
        inv_box.Add(invoice_label, 0, wx.BOTTOM, 10)
        inv_box.Add(self.invoice)

        amt_box = wx.BoxSizer(wx.VERTICAL)
        amt_box.Add(amount_label, 0, wx.BOTTOM, 10)
        amt_box.Add(self.amount)

        inv_amt = wx.BoxSizer(wx.HORIZONTAL)
        inv_amt.Add(inv_box, 0, wx.RIGHT, 10)
        inv_amt.Add(amt_box)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(inv_amt, 0, wx.ALL, 10)
        vbox.Add(card_label, 0, wx.LEFT | wx.RIGHT, 10)
        vbox.Add(self.source, 0, wx.EXPAND | wx.TOP | wx.LEFT | wx.RIGHT, 10)
        vbox.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL, 10)
        self.SetSizer(vbox)

        self.Bind(EVT_CREATE_CHARGE, self.on_charge_created)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)

        self.invoice.SetFocus()
        self.Fit()

    def on_ok(self, e):
        self.Disable()
        desc = self.invoice.GetValue()
        amt = int(self.amount.GetPlainValue())
        card_index = self.source.GetSelection()
        card = self.cards[card_index]
        if not desc:
            wx.MessageBox(
                'Must supply an invoice number.',
                'Error creating charge', wx.OK | wx.ICON_ERROR)
            self.Enable()
            return
        elif not amt:
            wx.MessageBox(
                'Must provide an amount to charge.',
                'Error creating charge', wx.OK | wx.ICON_ERROR)
            self.Enable()
            return
        elif card_index == wx.NOT_FOUND:
            wx.MessageBox(
                'Must select a payment source.',
                'Error creating charge', wx.OK | wx.ICON_ERROR)
            self.Enable()
            return
        t = threading.Thread(target=create_charge, args=(
            self, self.customer, card, amt, desc))
        t.setDaemon(True)
        t.start()

    def on_charge_created(self, e):
        charge = e.charge
        if not e.error:
            wx.MessageBox(
                'Card charged successfully.', 'Success',
                wx.OK | wx.ICON_INFORMATION)
            self.Parent.add_charge(charge)
            self.Destroy()
        else:
            error = e.error.json_body['error']
            wx.MessageBox(
                error['message'],
                'Error creating charge', wx.OK | wx.ICON_ERROR)
            self.Parent.add_charge(charge)
            self.Enable()


class CreateRefundDialog(wx.Dialog):
    def __init__(self, *args, **kwargs):
        self.charge = kwargs.pop('charge')
        super(CreateRefundDialog, self).__init__(*args, **kwargs)

        amount_label = wx.StaticText(self, label='Amount')
        self.amount = masked.numctrl.NumCtrl(self)
        self.amount.SetFractionWidth(2)
        self.amount.SetIntegerWidth(4)
        self.amount.SetAllowNegative(False)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(amount_label, 0, wx.ALL, 10)
        vbox.Add(self.amount, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        vbox.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL, 10)
        self.SetSizer(vbox)
        self.Fit()

        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.Bind(EVT_CREATE_REFUND, self.on_refund_created)

        self.amount.SetFocus()

    def on_ok(self, e):
        self.Disable()
        amt = int(self.amount.GetPlainValue())
        if not amt:
            wx.MessageBox(
                'Must provide an amount to refund.',
                'Error issuing refund', wx.OK | wx.ICON_ERROR)
            self.Enable()
            return
        t = threading.Thread(target=create_refund, args=(
            self, self.charge, amt))
        t.setDaemon(True)
        t.start()

    def on_refund_created(self, e):
        refund = e.refund
        if not e.error:
            wx.MessageBox(
                'Card refunded successfully.', 'Success',
                wx.OK | wx.ICON_INFORMATION)
            self.Parent.add_refund(refund, e.charge)
            self.Destroy()
        else:
            error = e.error.json_body['error']
            wx.MessageBox(
                error['message'],
                'Error issuing refund', wx.OK | wx.ICON_ERROR)
            self.Enable()

if __name__ == '__main__':
    app = wx.App(True, 'errors.log')
    frame = MainFrame(
        None, title='Stripe Card Terminal',
        style=wx.DEFAULT_FRAME_STYLE & ~(wx.RESIZE_BORDER | wx.MAXIMIZE_BOX))
    frame.Show()
    app.MainLoop()
