    import express from 'express';
    import bodyParser from 'body-parser';
    const app = express();
    app.use(bodyParser.json());
    const VERIFY_TOKEN = "aria-secret-123";
    app.get('/webhook', (req, res) => {
      const mode = req.query['hub.mode'];
      const token = req.query['hub.verify_token'];
      const challenge = req.query['hub.challenge'];
      if (mode && token === VERIFY_TOKEN) { res.status(200).send(challenge); } 
      else { res.sendStatus(403); }
    });
    app.post('/webhook', (req, res) => { console.log("Message:", req.body); res.sendStatus(200); });
    app.listen(process.env.PORT || 3000, () => console.log('ARIA live'));
