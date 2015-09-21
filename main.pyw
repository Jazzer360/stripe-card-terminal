import threading
import datetime
import ConfigParser

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


def fetch_customers(win):
    customers = []
    response = stripe.Customer.all()
    while True:
        for customer in response.data:
            customers.append(customer)
        if not response.has_more:
            break
        lastid = response.data[-1].id
        response = stripe.Customer.all(starting_after=lastid)
    wx.PostEvent(win, CustomersFetchedEvent(customers=customers))

def fetch_detail(win, customer):
    cards = []
    response = customer.sources.all()
    while True:
        for card in response.data:
            cards.append(card)
        if not response.has_more:
            break
        lastid = response.data[-1].id
        response = customer.sources.all(starting_after=lastid)
    
    charges = []
    response = stripe.Charge.all(customer=customer.id)
    while True:
        for charge in response.data:
            charges.append(charge)
        if not response.has_more:
            break
        lastid = response.data[-1].id
        response = stripe.Charge.all(customer=customer.id,
            starting_after=lastid)
    wx.PostEvent(win, CustomerDetailEvent(
        customer=customer, cards=cards, charges=charges))

def add_customer(win, email, description):
    customer = stripe.Customer.create(email=email, description=description)
    wx.PostEvent(win, AddCustomerEvent(customer=customer))

def add_card(win, customer, number, exp_month, exp_year, cvc=None):
    card = {
        'object': 'card',
        'number': int(number),
        'exp_month': int(exp_month),
        'exp_year': int(exp_year)}
    if cvc:
        card['cvc'] = int(cvc)
    try:
        card = customer.sources.create(source=card)
    except stripe.error.CardError as e:
        wx.PostEvent(win, AddCardEvent(error=e, card=None))
    else:
        wx.PostEvent(win, AddCardEvent(error=None, card=card))

def create_charge(win, customer, card, amount, description):
    try:
        charge = stripe.Charge.create(currency='usd', customer=customer.id,
            source=card.id, amount=amount, description=description)
    except stripe.error.CardError as e:
        charge = stripe.Charge.retrieve(e.json_body['error']['charge'])
        wx.PostEvent(win, CreateChargeEvent(error=e, charge=charge))
    else:
        wx.PostEvent(win, CreateChargeEvent(error=None, charge=charge))


class MainFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(MainFrame, self).__init__(*args, **kwargs)

        self.customer_list = CustomerList(self)
        self.customer_detail = CustomerDetail(self)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(self.customer_list, 0, wx.EXPAND)
        hbox.Add(self.customer_detail, 1, wx.EXPAND)
        self.SetSizer(hbox)

        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(EVT_CUSTOMERS_FETCHED, self.on_customers_fetched)
        self.Bind(EVT_CUSTOMER_DETAIL, self.on_detail_fetched)

        self.load_config()
        self.load_customers()
        self.Fit()

    def load_config(self):
        self.config = ConfigParser.SafeConfigParser()
        self.config.read('settings.cfg')
        stripe.api_key = self.config.get('Stripe', 'api_key')
        try:
            self.config.add_section('Stripe')
        except ConfigParser.DuplicateSectionError:
            pass

    def load_customers(self):
        self.customer_list.Disable()
        self.customer_detail.Disable()
        self.customer_detail.set_detail(None, None, None)
        t = threading.Thread(target=fetch_customers, args=(self,))
        t.setDaemon(True)
        t.start()

    def save_config(self):
        with open('settings.cfg', 'wb') as configfile:
            self.config.write(configfile)

    def display_customer_detail(self, customer):
        self.customer_list.Disable()
        self.customer_detail.Disable()
        t = threading.Thread(target=fetch_detail, args=(self, customer))
        t.setDaemon(True)
        t.start()
        return

    def on_close(self, e):
        self.save_config()
        e.Skip()

    def on_customers_fetched(self, e):
        self.customer_list.set_customers(e.customers)
        self.customer_list.Enable()
        self.Layout()

    def on_detail_fetched(self, e):
        self.customer_detail.set_detail(e.customer, e.cards, e.charges)
        self.customer_list.Enable()
        self.customer_detail.Enable()
        self.Layout()


class CustomerList(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(CustomerList, self).__init__(*args, **kwargs)

        label = wx.StaticText(self, label='Customers')
        self.listbox = wx.ListBox(self, style=wx.LB_SINGLE | wx.LB_SORT)
        add_button = wx.Button(self, label='Add Customer')
        reload_button = wx.Button(self, label='Reload')

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(label, 0, wx.ALIGN_CENTER|wx.ALL, 10)
        vbox.Add(self.listbox, 1, wx.EXPAND|wx.LEFT|wx.RIGHT, 10)
        vbox.Add(add_button, 0, wx.EXPAND|wx.TOP|wx.LEFT|wx.RIGHT, 10)
        vbox.Add(reload_button, 0, wx.EXPAND|wx.ALL, 10)
        self.SetSizer(vbox)

        self.listbox.Bind(wx.EVT_LISTBOX, self.on_selection)
        add_button.Bind(wx.EVT_BUTTON, self.on_add)
        reload_button.Bind(wx.EVT_BUTTON, self.on_refresh)

    def set_customers(self, customers):
        self.customers = customers
        self.listbox.Set([c.email for c in self.customers])

    def add_customer(self, customer):
        self.customers.append(customer)
        self.listbox.Set([c.email for c in self.customers])
        self.listbox.SetStringSelection(customer.email)
        self.on_selection(None)

    def on_add(self, e):
        dialog = AddCustomerDialog(self, title='Add Customer')
        dialog.ShowModal()
        dialog.Destroy()

    def on_refresh(self, e):
        self.Parent.load_customers()

    def on_selection(self, e):
        selection = self.listbox.GetStringSelection()
        for customer in self.customers:
            if selection == customer.email:
                self.Parent.display_customer_detail(customer)
                return


class CustomerDetail(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(CustomerDetail, self).__init__(*args, **kwargs)

        self.code = wx.StaticText(self)
        self.name = wx.StaticText(self)
        cards = wx.StaticText(self, label='Cards')
        add_card = wx.Button(self, label='Add Card')
        self.cards_list = CardList(self)
        charges = wx.StaticText(self, label='Charges')
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
        charges_header.Add(create_charge)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(self.code, 0, wx.ALIGN_CENTER|wx.ALL, 10)
        vbox.Add(self.name, 0, wx.ALIGN_CENTER|wx.LEFT|wx.RIGHT, 10)
        vbox.Add(card_header, 0, wx.EXPAND|wx.TOP|wx.LEFT|wx.RIGHT, 10)
        vbox.Add(self.cards_list, 1, wx.EXPAND|wx.TOP|wx.LEFT|wx.RIGHT, 10)
        vbox.Add(charges_header, 0, wx.EXPAND|wx.TOP|wx.LEFT|wx.RIGHT, 10)
        vbox.Add(self.charge_list, 1, wx.EXPAND|wx.ALL, 10)
        self.SetSizer(vbox)

        create_charge.Bind(wx.EVT_BUTTON, self.on_create_charge)
        add_card.Bind(wx.EVT_BUTTON, self.on_add_card)
        self.Disable()

    def set_detail(self, customer, cards, charges):
        self.customer = customer
        if customer:
            self.code.SetLabel(customer.email)
            self.name.SetLabel(customer.description)
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
            wx.MessageBox('Customer has no cards to charge.',
                'Error creating charge', wx.OK|wx.ICON_ERROR)
            return
        dialog = CreateChargeDialog(self, title='Charge Credit Card',
            customer=self.customer, cards=self.cards_list.cards)
        dialog.ShowModal()
        dialog.Destroy()


class CardList(wx.ListCtrl):
    def __init__(self, *args, **kwargs):
        super(CardList, self).__init__(style=wx.LC_REPORT, *args, **kwargs)
        self.InsertColumn(0, 'Card Info')
        self.InsertColumn(1, 'Expiration')
        self.cards = []

    def _resize_cols(self):
        self.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        self.SetColumnWidth(1, wx.LIST_AUTOSIZE_USEHEADER)

    def _fill_row(self, index, card):
        cardstr = '{} ending in {}'.format(card.brand, card.last4)
        exp = '{}/{}'.format(card.exp_month, card.exp_year)
        self.InsertStringItem(index, cardstr)
        self.SetStringItem(index, 1, exp)

    def set_cards(self, cards):
        self.cards = cards or []
        self.DeleteAllItems()
        if cards:
            for index, card in enumerate(cards):
                self._fill_row(index, card)
            self._resize_cols()

    def add_card(self, card):
        self.cards.insert(0, card)
        self._fill_row(0, card)
        self._resize_cols()


class ChargeList(wx.ListCtrl):
    def __init__(self, *args, **kwargs):
        super(ChargeList, self).__init__(style=wx.LC_REPORT, *args, **kwargs)
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

    def _fill_row(self, index, charge):
        date = datetime.date.fromtimestamp(charge.created).strftime('%x')
        amt = '${0:.02f}'.format(charge.amount / 100.0)
        card = '{} ending in {}'.format(
            charge.source.brand, charge.source.last4)
        exp = '{}/{}'.format(charge.source.exp_month, charge.source.exp_year)
        status = 'Success' if charge.status == 'succeeded' else 'Failed'
        self.InsertStringItem(index, date)
        self.SetStringItem(index, 1, amt)
        self.SetStringItem(index, 2, card)
        self.SetStringItem(index, 3, exp)
        self.SetStringItem(index, 4, status)

    def set_charges(self, charges):
        self.charges = charges or []
        self.DeleteAllItems()
        if charges:
            for index, charge in enumerate(charges):
                self._fill_row(index, charge)
            self._resize_cols()

    def add_charge(self, charge):
        self.charges.insert(0, charge)
        self._fill_row(0, charge)
        self._resize_cols()


class AddCustomerDialog(wx.Dialog):
    def __init__(self, *args, **kwargs):
        super(AddCustomerDialog, self).__init__(*args, **kwargs)

        code = wx.StaticText(self, label='Customer Code')
        self.code_entry = wx.TextCtrl(self)
        name = wx.StaticText(self, label='Customer Name')
        self.name_entry = wx.TextCtrl(self)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(code, 0, wx.ALL, 10)
        vbox.Add(self.code_entry, 0, wx.EXPAND|wx.LEFT|wx.RIGHT, 10)
        vbox.Add(name, 0, wx.TOP|wx.LEFT|wx.RIGHT, 10)
        vbox.Add(self.name_entry, 0, wx.EXPAND|wx.TOP|wx.LEFT|wx.RIGHT, 10)
        vbox.Add(self.CreateButtonSizer(wx.OK|wx.CANCEL), 0, wx.ALL, 10)
        self.SetSizer(vbox)

        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.Bind(EVT_ADD_CUSTOMER, self.on_customer_added)
        self.code_entry.SetFocus()
        self.Fit()

    def on_ok(self, e):
        self.Disable()
        email = self.code_entry.GetValue()
        desc = self.name_entry.GetValue()
        if not (email and desc):
            wx.MessageBox('Must supply customer code and customer name.',
                'Error adding customer', wx.OK|wx.ICON_ERROR)
            self.Enable()
            return
        elif email in (c.email for c in self.Parent.customers):
            wx.MessageBox('Customer already exists.',
                'Error adding customer', wx.OK|wx.ICON_ERROR)
            self.Enable()
            return
        t = threading.Thread(target=add_customer, args=(self, email, desc))
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
        self.cvc = masked.TextCtrl(self, mask=self.default_cvc,
            size=(45, -1))

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
        date_row.Add(year_box, 0, wx.LEFT|wx.RIGHT, 10)
        date_row.Add(cvc_box)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(cc_num_label, 0, wx.ALL, 10)
        vbox.Add(self.cc_num, 0, wx.EXPAND|wx.LEFT|wx.RIGHT, 10)
        vbox.Add(date_row, 0, wx.ALL, 10)
        vbox.Add(self.CreateButtonSizer(wx.OK|wx.CANCEL), 0, wx.ALL, 10)
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
            wx.MessageBox('Must supply card number and expiration.',
                'Error adding card', wx.OK|wx.ICON_ERROR)
            self.Enable()
            return
        t = threading.Thread(target=add_card, args=(
            self, self.Parent.customer, number, month, year, cvc))
        t.setDaemon(True)
        t.start()

    def on_card_added(self, e):
        card = e.card
        if card:
            self.Parent.add_card(card)
            self.Destroy()
        else:
            error = e.error.json_body['error']
            wx.MessageBox(error['message'],
                'Error adding card', wx.OK|wx.ICON_ERROR)
            self.Enable()


class CreateChargeDialog(wx.Dialog):
    def __init__(self, *args, **kwargs):
        self.customer = kwargs.pop('customer')
        self.cards = kwargs.pop('cards')
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
        vbox.Add(card_label, 0, wx.LEFT|wx.RIGHT, 10)
        vbox.Add(self.source, 0, wx.EXPAND|wx.TOP|wx.LEFT|wx.RIGHT, 10)
        vbox.Add(self.CreateButtonSizer(wx.OK|wx.CANCEL), 0, wx.ALL, 10)
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
            wx.MessageBox('Must supply an invoice number.',
                'Error creating charge', wx.OK|wx.ICON_ERROR)
            self.Enable()
            return
        elif not amt:
            wx.MessageBox('Must provide an amount to charge.',
                'Error creating charge', wx.OK|wx.ICON_ERROR)
            self.Enable()
            return
        elif card_index == wx.NOT_FOUND:
            wx.MessageBox('Must select a payment source.',
                'Error creating charge', wx.OK|wx.ICON_ERROR)
            self.Enable()
            return
        t = threading.Thread(target=create_charge, args=(
            self, self.customer, card, amt, desc))
        t.setDaemon(True)
        t.start()

    def on_charge_created(self, e):
        charge = e.charge
        if not e.error:
            wx.MessageBox('Card charged successfully.', 'Success',
                wx.OK|wx.ICON_INFORMATION)
            self.Parent.add_charge(charge)
            self.Destroy()
        else:
            error = e.error.json_body['error']
            wx.MessageBox(error['message'],
                'Error creating charge', wx.OK|wx.ICON_ERROR)
            self.Parent.add_charge(charge)
            self.Enable()


if __name__ == '__main__':
    app = wx.App(True, 'errors.log')
    frame = MainFrame(None, title='Stripe Card Terminal',
        style=wx.DEFAULT_FRAME_STYLE & ~(wx.RESIZE_BORDER | wx.MAXIMIZE_BOX))
    frame.Show()
    app.MainLoop()
